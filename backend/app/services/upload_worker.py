"""
Background Worker: FastAPI ilovasi ishga tushganda asyncio task sifatida ishga tushadi
va har 30 soniyada bir marta vaqti kelgan (scheduled_at <= now) shortslarni tekshirib,
ularni avtomatik YouTube'ga yuklaydi — har bir short o'z egasining (user_id) YouTube
kanaliga yuklanadi.

upload_short_now() — shu moduldagi umumiy (sync) yuklash mantig'i, "hozir yuklash"
tugmasi (shorts_router) va rejalashtirilgan avtomatik yuklash (scheduler_tick_loop)
ikkalasi ham shundan foydalanadi, shunda ikki xil kod saqlanmaydi.
"""
import asyncio
from pathlib import Path

from ..database import get_cursor
from ..services.scheduler_service import get_due_uploads
from ..services import youtube_service
from ..utils.logger import log, create_task, update_task

WORKER_INTERVAL_SECONDS = 30


async def scheduler_tick_loop():
    while True:
        try:
            await _process_due_uploads()
        except Exception as e:
            log(f"Scheduler worker xatosi: {e}", "error", "upload_worker")
        await asyncio.sleep(WORKER_INTERVAL_SECONDS)


async def _process_due_uploads():
    due = get_due_uploads()  # barcha foydalanuvchilar bo'yicha vaqti kelgan shortslar
    if not due:
        return

    for short in due:
        account = youtube_service.get_connected_account(short["user_id"])
        if not account.get("connected"):
            continue  # bu foydalanuvchi YouTube ulanmagan bo'lsa, uni o'tkazib yuboramiz
        upload_short_now(short)


def upload_short_now(short: dict) -> dict:
    """
    Bitta short'ni sinxron ravishda uning egasi (user_id) nomidan YouTube'ga yuklaydi.
    Navbat (job_queue) orqali chaqirilganda bir vaqtda faqat bitta yuklash ishlaydi.
    """
    short_id = short["id"]
    user_id = short["user_id"]
    if not short["file_path"] or not Path(short["file_path"]).exists():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET status='failed', error_message='Video fayl topilmadi' WHERE id=?",
                (short_id,),
            )
        return {"success": False, "message": "Video fayl topilmadi"}

    task_id = create_task("upload_youtube", short_id, "Yuklash boshlanmoqda...", user_id=user_id)
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE shorts SET status='uploading' WHERE id=?", (short_id,))

    def progress_cb(percent: int):
        update_task(task_id, progress=percent, message=f"Yuklanmoqda... {percent}%")

    hashtags_list = [h.strip() for h in (short["hashtags"] or "").replace("#", "").split() if h.strip()]
    keywords_list = [k.strip() for k in (short["keywords"] or "").split(",") if k.strip()]
    tags = list(dict.fromkeys(hashtags_list + keywords_list))

    result = youtube_service.upload_video(
        user_id=user_id,
        short_id=short_id,
        file_path=short["file_path"],
        title=short["title"] or f"Short #{short_id}",
        description=short["description"] or "",
        tags=tags,
        category_id=short["category_id"] or "22",
        visibility=short["visibility"] or "private",
        made_for_kids=bool(short["made_for_kids"]),
        playlist_id=short["playlist_id"],
        thumbnail_path=short["thumbnail_path"],
        progress_callback=progress_cb,
    )

    if result.get("success"):
        update_task(task_id, status="completed", progress=100, message="Yuklandi!")
    else:
        update_task(task_id, status="failed", message=result.get("message", "Noma'lum xato"))

    return result
