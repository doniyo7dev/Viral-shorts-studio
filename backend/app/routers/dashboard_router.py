"""
/api/dashboard — umumlashgan statistika, jarayon navbati, loglar,
real-time YouTube kanal statistikasi va fayl menejeri.
Har bir foydalanuvchi faqat o'z ma'lumotlarini (video, navbat, log, YouTube
kanal statistikasi, fayllar) ko'radi.
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends

from ..config import STORAGE_DIR, SHORTS_DIR, UPLOADS_DIR, THUMBNAILS_DIR
from ..database import get_cursor
from ..auth import get_current_user
from ..utils.logger import get_logs, get_tasks, get_active_tasks
from ..services import youtube_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(user: dict = Depends(get_current_user)):
    uid = user["id"]
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ?", (uid,))
        total_shorts = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ? AND status='uploaded'", (uid,))
        uploaded_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ? AND status='scheduled'", (uid,))
        scheduled_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ? AND status='draft'", (uid,))
        draft_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM shorts WHERE user_id = ? AND status='failed'", (uid,))
        failed_count = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM task_queue WHERE user_id = ? AND status IN ('queued','running')", (uid,)
        )
        queue_count = cur.fetchone()["cnt"]

    return {
        "total_shorts": total_shorts,
        "uploaded_count": uploaded_count, "scheduled_count": scheduled_count,
        "draft_count": draft_count, "failed_count": failed_count, "queue_count": queue_count,
    }


@router.get("/queue")
def get_queue(user: dict = Depends(get_current_user)):
    return get_active_tasks(user["id"])


@router.get("/tasks")
def get_all_tasks(limit: int = 100, user: dict = Depends(get_current_user)):
    return get_tasks(user["id"], limit)


@router.get("/logs")
def get_all_logs(limit: int = 200, level: str = None, user: dict = Depends(get_current_user)):
    return get_logs(user["id"], limit, level)


@router.get("/upload-history")
def get_upload_history(user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM shorts WHERE user_id = ? AND status = 'uploaded' ORDER BY uploaded_at DESC",
            (user["id"],),
        )
        return cur.fetchall()


# ==================== REAL-TIME YOUTUBE KANAL STATISTIKASI ====================

@router.get("/channel-stats")
def channel_stats(user: dict = Depends(get_current_user)):
    return youtube_service.get_channel_statistics(user["id"])


@router.get("/recent-videos")
def recent_videos(limit: int = 10, user: dict = Depends(get_current_user)):
    return youtube_service.get_recent_video_statistics(user["id"], max_results=limit)


# ==================== FILE MANAGER ====================

def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _owned_file_paths(user_id: int) -> set:
    """Joriy foydalanuvchiga tegishli barcha video/thumbnail fayl yo'llarini (basename) qaytaradi."""
    with get_cursor() as cur:
        cur.execute("SELECT file_path, thumbnail_path FROM shorts WHERE user_id = ?", (user_id,))
        rows = cur.fetchall()
    names = set()
    for r in rows:
        if r.get("file_path"):
            names.add(Path(r["file_path"]).name)
        if r.get("thumbnail_path"):
            names.add(Path(r["thumbnail_path"]).name)
    return names


@router.get("/files")
def list_files(folder: str = "shorts", user: dict = Depends(get_current_user)):
    folder_map = {"shorts": SHORTS_DIR, "uploads": UPLOADS_DIR, "thumbnails": THUMBNAILS_DIR}
    target = folder_map.get(folder)
    if target is None:
        raise HTTPException(400, "Noto'g'ri papka nomi")

    owned_names = _owned_file_paths(user["id"])

    files = []
    for f in sorted(target.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.name in owned_names:
            stat = f.stat()
            files.append({"name": f.name, "size_bytes": stat.st_size,
                           "size_human": _human_size(stat.st_size), "modified": stat.st_mtime})
    return files


@router.delete("/files/{folder}/{filename}")
def delete_file(folder: str, filename: str, user: dict = Depends(get_current_user)):
    folder_map = {"shorts": SHORTS_DIR, "uploads": UPLOADS_DIR, "thumbnails": THUMBNAILS_DIR}
    target_dir = folder_map.get(folder)
    if target_dir is None:
        raise HTTPException(400, "Noto'g'ri papka nomi")

    if filename not in _owned_file_paths(user["id"]):
        raise HTTPException(404, "Fayl topilmadi")

    file_path = (target_dir / filename).resolve()
    if not str(file_path).startswith(str(target_dir.resolve())):
        raise HTTPException(400, "Noto'g'ri fayl yo'li")
    if not file_path.exists():
        raise HTTPException(404, "Fayl topilmadi")

    file_path.unlink()
    return {"success": True}


@router.get("/storage-usage")
def get_storage_usage(user: dict = Depends(get_current_user)):
    owned_names = _owned_file_paths(user["id"])

    def owned_dir_size(path: Path) -> int:
        total = 0
        if path.exists():
            for f in path.iterdir():
                if f.is_file() and f.name in owned_names:
                    total += f.stat().st_size
        return total

    uploads_size = owned_dir_size(UPLOADS_DIR)
    shorts_size = owned_dir_size(SHORTS_DIR)
    thumbs_size = owned_dir_size(THUMBNAILS_DIR)

    return {
        "uploads": _human_size(uploads_size),
        "shorts": _human_size(shorts_size),
        "thumbnails": _human_size(thumbs_size),
        "total": _human_size(uploads_size + shorts_size + thumbs_size),
    }
