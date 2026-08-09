"""
Video boshqaruv xizmati (MySQL asosida). Har bir video foydalanuvchi tomonidan
qo'lda yuklanadi va o'z holida (tahrirsiz) saqlanadi. Har bir yozuv user_id
bilan bog'lanadi, shu bilan har bir foydalanuvchi faqat o'z videolarini
ko'radi/boshqaradi. Bu modul quyidagilarni ta'minlaydi:
  1. Yuklangan videoni 'shorts' jadvaliga yozish (default sarlavha/tavsif/hashtag/
     visibility sozlamalari — foydalanuvchining shaxsiy 'settings' yozuvlaridan)
  2. Ixtiyoriy qayta-eksport: subtitle, watermark, crop/format o'zgartirish
  3. Bir nechta videoni birlashtirish
"""
from pathlib import Path

from ..config import SHORTS_DIR, THUMBNAILS_DIR, TEMP_DIR, DEFAULT_OUTPUT_WIDTH, DEFAULT_OUTPUT_HEIGHT
from ..database import get_cursor
from ..utils.logger import log, create_task, update_task
from ..services import ffmpeg_service
from ..services.subtitle_service import generate_srt_from_text

DEFAULT_TITLE_TEMPLATE = "Video #{index}"
DEFAULT_DESCRIPTION_TEMPLATE = "Yangi qiziqarli video! #shorts"
DEFAULT_HASHTAGS = "#shorts #viral"
DEFAULT_VISIBILITY = "public"


def get_setting(user_id: int, key: str, default: str = "") -> str:
    with get_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE user_id = ? AND `key` = ?", (user_id, key))
        row = cur.fetchone()
    return row["value"] if row else default


def _get_short_owned(short_id: int, user_id: int = None) -> dict:
    with get_cursor() as cur:
        if user_id is not None:
            cur.execute("SELECT * FROM shorts WHERE id = ? AND user_id = ?", (short_id, user_id))
        else:
            cur.execute("SELECT * FROM shorts WHERE id = ?", (short_id,))
        return cur.fetchone()


def export_short(short_id: int, task_id: int = None, user_id: int = None):
    """Bitta video uchun: (ixtiyoriy) crop/format + subtitle + watermark + thumbnail qayta eksporti."""
    short = _get_short_owned(short_id, user_id)
    if not short:
        if task_id is not None:
            update_task(task_id, status="failed", message="Video topilmadi")
        return

    owner_id = short["user_id"]
    if task_id is None:
        task_id = create_task("export_short", short_id, "Render boshlandi...", user_id=owner_id)

    source_path = short.get("file_path")
    if not source_path or not Path(source_path).exists():
        update_task(task_id, status="failed", message="Manba video fayl topilmadi")
        return

    try:
        update_task(task_id, status="running", progress=10, message="Render bajarilmoqda...")
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE shorts SET status='processing' WHERE id=?", (short_id,))

        current_path = Path(source_path)
        crop_mode = short.get("crop_mode") or "none"

        if crop_mode != "none":
            meta = ffmpeg_service.probe_video(str(current_path))
            output_width = int(get_setting(owner_id, "output_width", str(DEFAULT_OUTPUT_WIDTH)))
            output_height = int(get_setting(owner_id, "output_height", str(DEFAULT_OUTPUT_HEIGHT)))
            reformatted = SHORTS_DIR / f"short_{short_id}_fmt.mp4"
            ffmpeg_service.trim_and_format_clip(
                source_path=str(current_path), output_path=str(reformatted),
                start=0, end=meta["duration"],
                src_width=meta["width"], src_height=meta["height"],
                target_width=output_width, target_height=output_height,
                crop_mode=crop_mode,
            )
            current_path = reformatted

        update_task(task_id, progress=50, message="Asosiy render tayyor.")

        if short.get("subtitle_enabled") and short.get("subtitle_text"):
            update_task(task_id, progress=65, message="Subtitr qo'shilmoqda...")
            meta = ffmpeg_service.probe_video(str(current_path))
            srt_path = TEMP_DIR / f"short_{short_id}.srt"
            generate_srt_from_text(short["subtitle_text"], meta["duration"], str(srt_path))
            subtitled_output = SHORTS_DIR / f"short_{short_id}_sub.mp4"
            ffmpeg_service.add_subtitle_burned(str(current_path), str(subtitled_output), str(srt_path))
            if current_path != Path(source_path):
                current_path.unlink(missing_ok=True)
            current_path = subtitled_output
            srt_path.unlink(missing_ok=True)

        if short.get("watermark_enabled") and short.get("watermark_path") and Path(short["watermark_path"]).exists():
            update_task(task_id, progress=80, message="Watermark qo'shilmoqda...")
            watermarked_output = SHORTS_DIR / f"short_{short_id}_wm.mp4"
            ffmpeg_service.add_watermark(str(current_path), str(watermarked_output), short["watermark_path"])
            if current_path != Path(source_path):
                current_path.unlink(missing_ok=True)
            current_path = watermarked_output

        final_output = SHORTS_DIR / f"short_{short_id}_final.mp4"
        if current_path != final_output:
            if current_path == Path(source_path):
                import shutil
                shutil.copy(str(current_path), str(final_output))
            else:
                current_path.rename(final_output)

        update_task(task_id, progress=90, message="Thumbnail yaratilmoqda...")
        meta = ffmpeg_service.probe_video(str(final_output))
        thumb_path = THUMBNAILS_DIR / f"short_{short_id}.jpg"
        ffmpeg_service.extract_thumbnail(str(final_output), str(thumb_path), timestamp=min(1.0, meta["duration"] / 4))

        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET file_path=?, thumbnail_path=?, duration=?, status='draft' WHERE id=?",
                (str(final_output), str(thumb_path), meta["duration"], short_id),
            )

        update_task(task_id, status="completed", progress=100, message="Render yakunlandi.")
        log(f"Video #{short_id} render qilindi", "success", "shorts_service", user_id=owner_id)

    except Exception as e:
        update_task(task_id, status="failed", message=str(e))
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE shorts SET status='failed', error_message=? WHERE id=?", (str(e), short_id))
        log(f"Video #{short_id} renderida xato: {e}", "error", "shorts_service", user_id=owner_id)


def reexport_short_with_options(short_id: int, crop_mode: str = None, subtitle_text: str = None,
                                 subtitle_enabled: bool = None, watermark_enabled: bool = None,
                                 watermark_path: str = None):
    """Foydalanuvchi tahrirlagan sozlamalar bilan videoni qayta render qiladi (navbatga)."""
    fields, values = [], []
    if crop_mode is not None:
        fields.append("crop_mode = ?"); values.append(crop_mode)
    if subtitle_text is not None:
        fields.append("subtitle_text = ?"); values.append(subtitle_text)
    if subtitle_enabled is not None:
        fields.append("subtitle_enabled = ?"); values.append(1 if subtitle_enabled else 0)
    if watermark_enabled is not None:
        fields.append("watermark_enabled = ?"); values.append(1 if watermark_enabled else 0)
    if watermark_path is not None:
        fields.append("watermark_path = ?"); values.append(watermark_path)

    if fields:
        values.append(short_id)
        with get_cursor(commit=True) as cur:
            cur.execute(f"UPDATE shorts SET {', '.join(fields)} WHERE id = ?", values)

    short = _get_short_owned(short_id)
    owner_id = short["user_id"] if short else 1
    task_id = create_task("export_short", short_id, "Render navbatda...", user_id=owner_id)
    export_short(short_id, task_id=task_id)


def create_manual_short(user_id: int, file_path: str, title: str = None, description: str = None,
                         hashtags: str = None, visibility: str = None) -> dict:
    """
    Yangi video yuklash: foydalanuvchi tanlagan fayl hech qanday tahrirlash yoki
    crop qilmasdan to'g'ridan-to'g'ri joriy foydalanuvchi nomiga ro'yxatga
    (asl fayl bilan) qo'shiladi. Title/Description berilmasa, foydalanuvchining
    shaxsiy Settings'dagi Default shabloni qo'llaniladi.
    """
    title_template = get_setting(user_id, "default_title_template", DEFAULT_TITLE_TEMPLATE)
    description_template = get_setting(user_id, "default_description_template", DEFAULT_DESCRIPTION_TEMPLATE)
    default_hashtags = get_setting(user_id, "default_hashtags", DEFAULT_HASHTAGS)

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ?", (user_id,))
        existing_count = cur.fetchone()["cnt"]

    final_title = title or title_template.format(index=existing_count + 1, project_name="Video")
    final_visibility = visibility or DEFAULT_VISIBILITY

    thumb_path = THUMBNAILS_DIR / f"short_manual_{Path(file_path).stem}.jpg"
    try:
        ffmpeg_service.extract_thumbnail(str(file_path), str(thumb_path), timestamp=0.5)
    except Exception as e:
        log(f"Thumbnail yaratib bo'lmadi: {e}", "warning", "shorts_service", user_id=user_id)
        thumb_path = None

    try:
        meta = ffmpeg_service.probe_video(str(file_path))
        duration = meta.get("duration", 0)
    except Exception:
        duration = 0

    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO shorts
               (user_id, file_path, thumbnail_path, start_time, end_time, duration, score,
                title, description, hashtags, crop_mode, status, manual_upload, visibility)
               VALUES (?, ?, ?, 0, ?, ?, 0, ?, ?, ?, 'none', 'draft', 1, ?)""",
            (user_id, str(file_path), str(thumb_path) if thumb_path else None, duration, duration,
             final_title, description if description is not None else description_template,
             hashtags if hashtags is not None else default_hashtags, final_visibility),
        )
        short_id = cur.lastrowid

    log(f"Yangi video #{short_id} yuklandi", "success", "shorts_service", user_id=user_id)
    return {"success": True, "short_id": short_id}


def merge_shorts(user_id: int, short_ids: list, new_title: str = "Birlashtirilgan video") -> dict:
    """Joriy foydalanuvchiga tegishli bir nechta videoni bitta faylga birlashtiradi va yangi yozuv yaratadi."""
    with get_cursor() as cur:
        placeholders = ",".join(["?"] * len(short_ids))
        cur.execute(
            f"SELECT * FROM shorts WHERE user_id = ? AND id IN ({placeholders}) ORDER BY created_at",
            [user_id] + short_ids,
        )
        rows = cur.fetchall()

    if len(rows) < 2:
        return {"success": False, "message": "Kamida 2 ta video kerak."}

    clip_paths = [r["file_path"] for r in rows if r.get("file_path") and Path(r["file_path"]).exists()]
    if len(clip_paths) < 2:
        return {"success": False, "message": "Birlashtirish uchun fayllar topilmadi."}

    total_duration = sum(r["duration"] for r in rows)

    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO shorts
               (user_id, start_time, end_time, duration, score, title, crop_mode, status, manual_upload, visibility)
               VALUES (?, 0, ?, ?, 0, ?, 'none', 'processing', 1, ?)""",
            (user_id, total_duration, total_duration, new_title, DEFAULT_VISIBILITY),
        )
        new_short_id = cur.lastrowid

    try:
        output_path = SHORTS_DIR / f"short_{new_short_id}_final.mp4"
        ffmpeg_service.merge_clips(clip_paths, str(output_path))

        thumb_path = THUMBNAILS_DIR / f"short_{new_short_id}.jpg"
        ffmpeg_service.extract_thumbnail(str(output_path), str(thumb_path), timestamp=1.0)

        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET file_path=?, thumbnail_path=?, status='draft' WHERE id=?",
                (str(output_path), str(thumb_path), new_short_id),
            )
        log(f"{len(clip_paths)} ta video birlashtirildi -> yangi video #{new_short_id}",
            "success", "shorts_service", user_id=user_id)
        return {"success": True, "short_id": new_short_id}
    except Exception as e:
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE shorts SET status='failed', error_message=? WHERE id=?", (str(e), new_short_id))
        return {"success": False, "message": str(e)}
