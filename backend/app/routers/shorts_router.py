"""
/api/shorts — Yuklangan videolarni boshqarish: ro'yxat, tafsilot, tahrirlash,
qayta render, birlashtirish, o'chirish, AI (Groq) orqali video tahlili va
SEO metadata generatsiya, video yuklash.

Har bir so'rov joriy foydalanuvchi (get_current_user) bo'yicha filtrlanadi,
shu bilan har kim faqat o'zi yuklagan videolarni ko'radi/boshqaradi.
"""
import shutil
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from typing import Optional, List

from ..config import WATERMARKS_DIR, STORAGE_DIR, UPLOADS_DIR, ALLOWED_VIDEO_EXTENSIONS, MAX_UPLOAD_SIZE_MB
from ..database import get_cursor
from ..auth import get_current_user
from ..services.shorts_service import reexport_short_with_options, merge_shorts, export_short, create_manual_short
from ..services.groq_service import generate_metadata_for_short, analyze_video_content
from ..services.job_queue import submit_job
from ..services.upload_worker import upload_short_now
from ..services import youtube_service
from ..utils.logger import log, create_task

router = APIRouter(prefix="/api/shorts", tags=["shorts"])


def _to_media_url(abs_path: str) -> str:
    if not abs_path:
        return None
    try:
        rel = Path(abs_path).resolve().relative_to(STORAGE_DIR.resolve())
        return f"/media/{rel.as_posix()}"
    except Exception:
        return None


def _enrich(row: dict) -> dict:
    row["thumbnail_url"] = _to_media_url(row.get("thumbnail_path"))
    row["video_url"] = _to_media_url(row.get("file_path"))
    return row


def _get_owned_short(short_id: int, user_id: int) -> dict:
    """Short'ni faqat joriy foydalanuvchiga tegishli bo'lsagina qaytaradi, aks holda 404."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM shorts WHERE id = ? AND user_id = ?", (short_id, user_id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Video topilmadi")
    return row


@router.get("")
def list_shorts(status: Optional[str] = None, manual_only: Optional[bool] = None,
                 user: dict = Depends(get_current_user)):
    query = "SELECT * FROM shorts WHERE user_id = ?"
    params = [user["id"]]
    if status:
        query += " AND status = ?"
        params.append(status)
    if manual_only:
        query += " AND manual_upload = 1"
    query += " ORDER BY created_at DESC"

    with get_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_enrich(r) for r in rows]


@router.get("/{short_id}")
def get_short(short_id: int, user: dict = Depends(get_current_user)):
    row = _get_owned_short(short_id, user["id"])
    return _enrich(row)


class ShortUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    hashtags: Optional[str] = None
    keywords: Optional[str] = None
    playlist_id: Optional[str] = None
    category_id: Optional[str] = None
    visibility: Optional[str] = None
    made_for_kids: Optional[bool] = None
    crop_mode: Optional[str] = None


@router.patch("/{short_id}")
def update_short(short_id: int, payload: ShortUpdate, user: dict = Depends(get_current_user)):
    _get_owned_short(short_id, user["id"])

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return {"success": True, "message": "O'zgarish yo'q"}

    fields, values = [], []
    for k, v in data.items():
        if k == "made_for_kids":
            v = 1 if v else 0
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(short_id)

    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE shorts SET {', '.join(fields)} WHERE id = ?", values)
    return {"success": True}


class SubtitleUpdate(BaseModel):
    subtitle_text: str
    subtitle_enabled: bool = True


@router.post("/{short_id}/subtitle")
def set_subtitle(short_id: int, payload: SubtitleUpdate, user: dict = Depends(get_current_user)):
    _get_owned_short(short_id, user["id"])

    submit_job(
        reexport_short_with_options, label=f"subtitle_short_{short_id}",
        short_id=short_id, subtitle_text=payload.subtitle_text, subtitle_enabled=payload.subtitle_enabled,
    )
    return {"success": True, "message": "Subtitr bilan qayta render navbatga qo'shildi."}


@router.post("/{short_id}/watermark")
async def set_watermark(short_id: int, enabled: bool, file: Optional[UploadFile] = File(None),
                         user: dict = Depends(get_current_user)):
    _get_owned_short(short_id, user["id"])

    watermark_path = None
    if file:
        ext = Path(file.filename).suffix.lower() or ".png"
        watermark_path = WATERMARKS_DIR / f"wm_{short_id}{ext}"
        with open(watermark_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        watermark_path = str(watermark_path)

    submit_job(
        reexport_short_with_options, label=f"watermark_short_{short_id}",
        short_id=short_id, watermark_enabled=enabled, watermark_path=watermark_path,
    )
    return {"success": True, "message": "Watermark bilan qayta render navbatga qo'shildi."}


@router.post("/{short_id}/crop")
def set_crop_mode(short_id: int, crop_mode: str, user: dict = Depends(get_current_user)):
    if crop_mode not in ("smart", "center", "top", "blur_pad", "none"):
        raise HTTPException(400, "Noto'g'ri crop mode")

    _get_owned_short(short_id, user["id"])

    submit_job(
        reexport_short_with_options, label=f"crop_short_{short_id}",
        short_id=short_id, crop_mode=crop_mode,
    )
    return {"success": True, "message": "Yangi format bilan qayta render navbatga qo'shildi."}


@router.post("/{short_id}/render")
def render_now(short_id: int, user: dict = Depends(get_current_user)):
    """Video'ni navbatga qo'shib qayta render qiladi (masalan tahrirlardan keyin)."""
    _get_owned_short(short_id, user["id"])

    task_id = create_task("export_short", short_id, "Render navbatda...", user_id=user["id"])
    submit_job(export_short, short_id, label=f"render_short_{short_id}", task_id=task_id)
    return {"success": True, "message": "Render navbatga qo'shildi."}


@router.post("/{short_id}/upload-now")
def upload_now(short_id: int, user: dict = Depends(get_current_user)):
    """Video'ni navbatni kutmasdan darhol YouTube'ga yuklashni navbatga qo'shadi."""
    account = youtube_service.get_connected_account(user["id"])
    if not account.get("connected"):
        raise HTTPException(400, "YouTube akkaunt ulanmagan. Avval Settings > YouTube bo'limida ulaning.")

    row = _get_owned_short(short_id, user["id"])
    if not row.get("file_path") or not Path(row["file_path"]).exists():
        raise HTTPException(400, "Video fayl topilmadi")

    submit_job(upload_short_now, row, label=f"upload_now_short_{short_id}")
    return {"success": True, "message": "Yuklash navbatga qo'shildi."}


@router.post("/upload-manual")
async def upload_manual(file: UploadFile = File(...), title: Optional[str] = Form(None),
                         description: Optional[str] = Form(None), hashtags: Optional[str] = Form(None),
                         visibility: Optional[str] = Form(None),
                         user: dict = Depends(get_current_user)):
    """
    Yangi video yuklash: fayl hech qanday tahrirlash, crop yoki formatlashtirmasdan
    asl holida saqlanadi. Fayl saqlash tezkor (katta chunk, streaming) — thumbnail/
    probe orqa fonda amalga oshiriladi, shu bilan foydalanuvchi darhol javob oladi.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Qo'llab-quvvatlanmaydigan format: {ext}")

    if visibility and visibility not in ("public", "private", "unlisted"):
        raise HTTPException(400, "Noto'g'ri visibility qiymati")

    dest_path = UPLOADS_DIR / f"manual_{user['id']}_{int(time.time() * 1000)}{ext}"

    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    written = 0
    try:
        with open(dest_path, "wb") as f:
            while True:
                chunk = await file.read(4 * 1024 * 1024)  # 4MB chunk — tezroq yozish
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(400, f"Fayl juda katta. Maksimal hajm: {MAX_UPLOAD_SIZE_MB}MB")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Fayl saqlashda xato: {e}")

    result = create_manual_short(
        user_id=user["id"], file_path=str(dest_path), title=title, description=description,
        hashtags=hashtags, visibility=visibility,
    )
    log(f"Yangi video yuklandi: {file.filename}", "success", "shorts_router", user_id=user["id"])
    return result


class MergeRequest(BaseModel):
    short_ids: List[int]
    title: str = "Birlashtirilgan video"


@router.post("/merge")
def merge(payload: MergeRequest, user: dict = Depends(get_current_user)):
    if len(payload.short_ids) < 2:
        raise HTTPException(400, "Kamida 2 ta video tanlang")
    result = merge_shorts(user["id"], payload.short_ids, payload.title)
    if not result.get("success"):
        raise HTTPException(400, result.get("message", "Birlashtirishda xato"))
    return result


@router.post("/cancel-all-scheduled")
def cancel_all_scheduled(user: dict = Depends(get_current_user)):
    """Joriy foydalanuvchining barcha 'scheduled' holatidagi videolarini bekor qilib, Draft holatiga qaytaradi."""
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE status = 'scheduled' AND user_id = ?", (user["id"],))
        count = cur.fetchone()["cnt"]
        cur.execute(
            "UPDATE shorts SET status='draft', scheduled_at=NULL WHERE status='scheduled' AND user_id = ?",
            (user["id"],),
        )

    log(f"{count} ta rejalashtirilgan video bekor qilindi (Draft holatiga qaytarildi)",
        "info", "shorts_router", user_id=user["id"])
    return {"success": True, "cancelled_count": count}


class BulkMetadataUpdate(BaseModel):
    short_ids: List[int]
    title: Optional[str] = None
    description: Optional[str] = None
    hashtags: Optional[str] = None
    keywords: Optional[str] = None


@router.post("/bulk-metadata")
def bulk_update_metadata(payload: BulkMetadataUpdate, user: dict = Depends(get_current_user)):
    if not payload.short_ids:
        raise HTTPException(400, "Kamida bitta video tanlang")

    fields, values = [], []
    if payload.title is not None:
        fields.append("title = ?"); values.append(payload.title)
    if payload.description is not None:
        fields.append("description = ?"); values.append(payload.description)
    if payload.hashtags is not None:
        fields.append("hashtags = ?"); values.append(payload.hashtags)
    if payload.keywords is not None:
        fields.append("keywords = ?"); values.append(payload.keywords)

    if not fields:
        raise HTTPException(400, "Kamida bitta maydon (title/description/hashtags/keywords) berilishi kerak")

    placeholders = ",".join(["?"] * len(payload.short_ids))
    query = f"UPDATE shorts SET {', '.join(fields)} WHERE user_id = ? AND id IN ({placeholders})"

    with get_cursor(commit=True) as cur:
        cur.execute(query, values + [user["id"]] + payload.short_ids)
        updated_count = cur.rowcount

    log(f"{updated_count} ta video uchun umumiy metadata qo'llanildi", "success", "shorts_router", user_id=user["id"])
    return {"success": True, "updated_count": updated_count}


@router.post("/{short_id}/analyze")
def analyze_content(short_id: int, user: dict = Depends(get_current_user)):
    """
    AI video tahlili: audio transkripsiya (Groq Whisper) + mavzu/til/kategoriya/
    kalit so'zlar/viral tavsiyalar (Groq LLM). Natija keshlanadi.
    """
    _get_owned_short(short_id, user["id"])

    result = analyze_video_content(user["id"], short_id, force=True)
    if not result.get("success"):
        raise HTTPException(400, result.get("message", "Tahlilda xato"))
    return result


@router.post("/{short_id}/generate-metadata")
def generate_metadata(short_id: int, user: dict = Depends(get_current_user)):
    _get_owned_short(short_id, user["id"])

    result = generate_metadata_for_short(user["id"], short_id)
    if not result.get("success"):
        raise HTTPException(400, result.get("message", "Metadata generatsiyasida xato"))
    return result


@router.delete("/{short_id}")
def delete_short(short_id: int, user: dict = Depends(get_current_user)):
    row = _get_owned_short(short_id, user["id"])

    if row.get("file_path"):
        Path(row["file_path"]).unlink(missing_ok=True)
    if row.get("thumbnail_path"):
        Path(row["thumbnail_path"]).unlink(missing_ok=True)

    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM shorts WHERE id = ?", (short_id,))

    log(f"Video #{short_id} o'chirildi", "info", "shorts_router", user_id=user["id"])
    return {"success": True}
