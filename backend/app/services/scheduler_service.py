"""
Calendar Scheduler mantig'i (MySQL asosida):
  - Schedule slotlarni boshqarish
  - Auto Schedule ('kuniga N ta, X soatlarda')
  - Interval Schedule ('har N soat/kunda bittadan')
  - Draft shortslarni bo'sh vaqt kataklariga avtomatik taqsimlash
  - Vaqti kelgan shortslarni aniqlash (upload worker chaqiradi)
Barcha vaqtlar foydalanuvchi tanlagan timezone bo'yicha hisoblanadi,
DB'da har doim UTC saqlanadi. Schedule slotlar, sozlamalar va shortslar
har bir foydalanuvchi (user_id) uchun alohida.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..database import get_cursor
from ..utils.logger import log


def get_timezone_name(user_id: int) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE user_id = ? AND `key` = 'timezone'", (user_id,))
        row = cur.fetchone()
    return row["value"] if row else "Asia/Tashkent"


def get_local_tz(user_id: int) -> ZoneInfo:
    return ZoneInfo(get_timezone_name(user_id))


def local_to_utc_iso(dt_local: datetime, user_id: int) -> str:
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=get_local_tz(user_id))
    return dt_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")


def utc_naive_to_local(dt, user_id: int) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_local_tz(user_id))


# ==================== SCHEDULE SLOTS ====================

def get_schedule_slots(user_id: int) -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM schedule_slots WHERE user_id = ? AND enabled = 1 ORDER BY hour, minute", (user_id,)
        )
        return cur.fetchall()


def get_all_schedule_slots(user_id: int) -> list:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM schedule_slots WHERE user_id = ? ORDER BY hour, minute", (user_id,))
        return cur.fetchall()


def add_schedule_slot(user_id: int, hour: int, minute: int) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO schedule_slots (user_id, hour, minute, enabled) VALUES (?, ?, ?, 1)",
            (user_id, hour, minute),
        )
        return cur.lastrowid


def remove_schedule_slot(user_id: int, slot_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM schedule_slots WHERE id = ? AND user_id = ?", (slot_id, user_id))


def toggle_schedule_slot(user_id: int, slot_id: int, enabled: bool):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE schedule_slots SET enabled = ? WHERE id = ? AND user_id = ?",
            (1 if enabled else 0, slot_id, user_id),
        )


# ==================== AUTO SCHEDULE ====================

def auto_schedule_drafts(user_id: int, daily_count: int = None, start_date: datetime = None) -> dict:
    tz = get_local_tz(user_id)
    if start_date is None:
        start_date = datetime.now(tz)

    with get_cursor() as cur:
        cur.execute("SELECT * FROM shorts WHERE user_id = ? AND status = 'draft' ORDER BY created_at ASC", (user_id,))
        draft_shorts = cur.fetchall()

    if not draft_shorts:
        return {"success": True, "scheduled_count": 0, "message": "Draft holatidagi shorts topilmadi."}

    slots = get_schedule_slots(user_id)
    if not slots:
        return {"success": False, "scheduled_count": 0, "message": "Schedule slotlar sozlanmagan."}

    if daily_count and daily_count < len(slots):
        slots = slots[:daily_count]
    elif daily_count and daily_count > len(slots):
        slots = _expand_slots_to_count(slots, daily_count)

    with get_cursor() as cur:
        cur.execute(
            "SELECT scheduled_at FROM shorts WHERE user_id = ? AND "
            "status IN ('scheduled','processing','uploading','uploaded') AND scheduled_at IS NOT NULL",
            (user_id,),
        )
        occupied = {str(r["scheduled_at"]) for r in cur.fetchall()}

    scheduled_count = 0
    day_offset = 0
    slot_idx = 0
    max_days_ahead = 90

    with get_cursor(commit=True) as cur:
        for short in draft_shorts:
            placed = False
            attempts = 0
            while not placed and attempts < max_days_ahead * len(slots):
                slot = slots[slot_idx % len(slots)]
                candidate_date = (start_date + timedelta(days=day_offset)).replace(
                    hour=slot["hour"], minute=slot["minute"], second=0, microsecond=0
                )
                if candidate_date > datetime.now(tz):
                    candidate_utc = local_to_utc_iso(candidate_date, user_id)
                    if candidate_utc not in occupied:
                        cur.execute(
                            "UPDATE shorts SET status='scheduled', scheduled_at=? WHERE id=?",
                            (candidate_utc, short["id"]),
                        )
                        occupied.add(candidate_utc)
                        scheduled_count += 1
                        placed = True

                slot_idx += 1
                if slot_idx % len(slots) == 0:
                    day_offset += 1
                attempts += 1

    log(f"Auto Schedule: {scheduled_count} ta short vaqt kataklariga joylashtirildi",
        "success", "scheduler_service", user_id=user_id)
    return {"success": True, "scheduled_count": scheduled_count}


def _expand_slots_to_count(base_slots: list, target_count: int) -> list:
    if target_count <= len(base_slots):
        return base_slots[:target_count]

    day_start_minutes = 6 * 60
    day_end_minutes = 23 * 60 + 59
    span = day_end_minutes - day_start_minutes
    step = span // target_count

    generated = []
    for i in range(target_count):
        total_min = day_start_minutes + i * step
        generated.append({"hour": total_min // 60, "minute": total_min % 60})
    return generated


def simple_schedule_mode(user_id: int, daily_count: int, hours: list) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM schedule_slots WHERE user_id = ?", (user_id,))
        for h in hours:
            hour, minute = map(int, h.split(":"))
            cur.execute(
                "INSERT INTO schedule_slots (user_id, hour, minute, enabled) VALUES (?, ?, ?, 1)",
                (user_id, hour, minute),
            )
        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'daily_upload_count', ?) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)", (user_id, str(daily_count))
        )
        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'auto_schedule_mode', 'simple') "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)", (user_id,)
        )

    return auto_schedule_drafts(user_id, daily_count=daily_count)


def interval_schedule_drafts(user_id: int, interval_hours: float, start_at: datetime = None) -> dict:
    """
    Oddiy interval rejimi: "har N soatda bittadan qo'y". Joriy foydalanuvchining
    barcha 'draft' holatidagi shortslarini yaratilgan tartibda, bir-biridan
    interval_hours soat farq bilan navbat bilan rejalashtiradi.
    """
    tz = get_local_tz(user_id)
    if interval_hours <= 0:
        return {"success": False, "scheduled_count": 0, "message": "Interval musbat bo'lishi kerak."}

    if start_at is None:
        start_at = datetime.now(tz) + timedelta(hours=interval_hours)
    elif start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=tz)

    with get_cursor() as cur:
        cur.execute("SELECT * FROM shorts WHERE user_id = ? AND status = 'draft' ORDER BY created_at ASC", (user_id,))
        draft_shorts = cur.fetchall()

    if not draft_shorts:
        return {"success": True, "scheduled_count": 0, "message": "Draft holatidagi shorts topilmadi."}

    with get_cursor() as cur:
        cur.execute(
            "SELECT scheduled_at FROM shorts WHERE user_id = ? AND "
            "status IN ('scheduled','processing','uploading','uploaded') AND scheduled_at IS NOT NULL",
            (user_id,),
        )
        occupied = {str(r["scheduled_at"]) for r in cur.fetchall()}

    scheduled_count = 0
    cursor_time = start_at
    max_attempts_per_short = 200

    with get_cursor(commit=True) as cur:
        for short in draft_shorts:
            attempts = 0
            while attempts < max_attempts_per_short:
                candidate_utc = local_to_utc_iso(cursor_time, user_id)
                if candidate_utc not in occupied:
                    cur.execute(
                        "UPDATE shorts SET status='scheduled', scheduled_at=? WHERE id=?",
                        (candidate_utc, short["id"]),
                    )
                    occupied.add(candidate_utc)
                    scheduled_count += 1
                    cursor_time = cursor_time + timedelta(hours=interval_hours)
                    break
                cursor_time = cursor_time + timedelta(hours=interval_hours)
                attempts += 1

        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'auto_schedule_mode', 'interval') "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)", (user_id,)
        )
        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'interval_hours', ?) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)", (user_id, str(interval_hours))
        )

    log(f"Interval Schedule: {scheduled_count} ta short {interval_hours} soatlik oraliq bilan joylashtirildi",
        "success", "scheduler_service", user_id=user_id)
    return {"success": True, "scheduled_count": scheduled_count}


def get_due_uploads() -> list:
    """Barcha foydalanuvchilar bo'yicha vaqti kelgan (scheduled) shortslarni qaytaradi."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM shorts WHERE status = 'scheduled' AND scheduled_at <= UTC_TIMESTAMP() "
            "ORDER BY scheduled_at ASC"
        )
        return cur.fetchall()


def get_calendar_events(user_id: int, start_utc: str, end_utc: str) -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM shorts WHERE user_id = ? AND scheduled_at BETWEEN ? AND ? ORDER BY scheduled_at ASC",
            (user_id, start_utc, end_utc),
        )
        shorts = cur.fetchall()
    return shorts


def reschedule_short(user_id: int, short_id: int, new_local_datetime: datetime) -> dict:
    tz = get_local_tz(user_id)
    if new_local_datetime.tzinfo is None:
        new_local_datetime = new_local_datetime.replace(tzinfo=tz)
    new_utc = local_to_utc_iso(new_local_datetime, user_id)

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT status FROM shorts WHERE id = ? AND user_id = ?", (short_id, user_id))
        row = cur.fetchone()
        if not row:
            return {"success": False, "message": "Video topilmadi"}
        new_status = row["status"] if row["status"] != "draft" else "scheduled"
        cur.execute(
            "UPDATE shorts SET scheduled_at = ?, status = ? WHERE id = ? AND user_id = ?",
            (new_utc, new_status, short_id, user_id),
        )
    return {"success": True, "scheduled_at": new_utc}
