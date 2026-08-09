"""
Ilova ichi loglash va task-queue progress yangilash (MySQL asosida).
Har bir yozuv user_id bilan bog'lanadi, shu bilan har bir foydalanuvchi
faqat o'z loglari/tasklarini ko'radi (Dashboard sahifasida).
"""
from ..database import get_cursor


def log(message: str, level: str = "info", source: str = "app", user_id: int = 1):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO logs (user_id, level, source, message) VALUES (?, ?, ?, ?)",
            (user_id, level, source, message),
        )
    print(f"[{level.upper()}] [{source}] (user={user_id}) {message}")


def get_logs(user_id: int, limit: int = 200, level: str = None):
    with get_cursor() as cur:
        if level:
            cur.execute(
                "SELECT * FROM logs WHERE user_id = ? AND level = ? ORDER BY id DESC LIMIT ?",
                (user_id, level, limit),
            )
        else:
            cur.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return cur.fetchall()


# ---------------- Task Queue ----------------

def create_task(task_type: str, ref_id: int = None, message: str = "", user_id: int = 1) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO task_queue (user_id, task_type, ref_id, status, progress, message) "
            "VALUES (?, ?, ?, 'queued', 0, ?)",
            (user_id, task_type, ref_id, message),
        )
        return cur.lastrowid


def update_task(task_id: int, status: str = None, progress: int = None, message: str = None):
    fields, values = [], []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if message is not None:
        fields.append("message = ?")
        values.append(message)
    if not fields:
        return
    values.append(task_id)
    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE task_queue SET {', '.join(fields)} WHERE id = ?", values)


def get_tasks(user_id: int, limit: int = 100):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM task_queue WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return cur.fetchall()


def get_active_tasks(user_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM task_queue WHERE user_id = ? AND status IN ('queued', 'running') ORDER BY id ASC",
            (user_id,),
        )
        return cur.fetchall()
