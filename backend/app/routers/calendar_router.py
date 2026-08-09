"""
/api/calendar — Calendar Scheduler backend: schedule slotlar CRUD, Auto Schedule,
Interval Schedule (oddiy "har N soatda"), kalendar hodisalarini (day/week/month) olish,
drag & drop orqali qayta rejalashtirish. Har bir foydalanuvchi o'zining alohida
schedule slotlari va shortslariga ega.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

from ..services import scheduler_service
from ..database import get_cursor
from ..auth import get_current_user
from .shorts_router import _enrich

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


# ==================== SCHEDULE SLOTS ====================

@router.get("/slots")
def list_slots(user: dict = Depends(get_current_user)):
    return scheduler_service.get_all_schedule_slots(user["id"])


class SlotPayload(BaseModel):
    hour: int
    minute: int = 0


@router.post("/slots")
def add_slot(payload: SlotPayload, user: dict = Depends(get_current_user)):
    if not (0 <= payload.hour <= 23) or not (0 <= payload.minute <= 59):
        raise HTTPException(400, "Noto'g'ri vaqt")
    slot_id = scheduler_service.add_schedule_slot(user["id"], payload.hour, payload.minute)
    return {"success": True, "id": slot_id}


@router.delete("/slots/{slot_id}")
def delete_slot(slot_id: int, user: dict = Depends(get_current_user)):
    scheduler_service.remove_schedule_slot(user["id"], slot_id)
    return {"success": True}


class SlotToggle(BaseModel):
    enabled: bool


@router.patch("/slots/{slot_id}")
def toggle_slot(slot_id: int, payload: SlotToggle, user: dict = Depends(get_current_user)):
    scheduler_service.toggle_schedule_slot(user["id"], slot_id, payload.enabled)
    return {"success": True}


# ==================== KALENDAR HODISALARI ====================

@router.get("/events")
def get_events(start: str, end: str, user: dict = Depends(get_current_user)):
    """start/end — ISO formatdagi UTC sanalar (frontend local vaqtni UTC'ga o'zi konvert qiladi)."""
    events = scheduler_service.get_calendar_events(user["id"], start, end)
    return [_enrich(e) for e in events]


class RescheduleRequest(BaseModel):
    short_id: int
    new_datetime_local: str  # ISO format, timezone belgisiz (local vaqt sifatida talqin qilinadi)


@router.post("/reschedule")
def reschedule(payload: RescheduleRequest, user: dict = Depends(get_current_user)):
    try:
        dt = datetime.fromisoformat(payload.new_datetime_local)
    except ValueError:
        raise HTTPException(400, "Noto'g'ri sana formati")
    result = scheduler_service.reschedule_short(user["id"], payload.short_id, dt)
    return result


# ==================== AUTO SCHEDULE ====================

class AutoScheduleRequest(BaseModel):
    daily_count: Optional[int] = None


@router.post("/auto-schedule")
def auto_schedule(payload: AutoScheduleRequest, user: dict = Depends(get_current_user)):
    result = scheduler_service.auto_schedule_drafts(user["id"], daily_count=payload.daily_count)
    return result


class SimpleScheduleRequest(BaseModel):
    daily_count: int
    hours: List[str]  # ["09:00", "18:00"]


@router.post("/simple-schedule")
def simple_schedule(payload: SimpleScheduleRequest, user: dict = Depends(get_current_user)):
    if payload.daily_count < 1:
        raise HTTPException(400, "daily_count kamida 1 bo'lishi kerak")
    if not payload.hours:
        raise HTTPException(400, "Kamida bitta soat kiritilishi kerak")
    result = scheduler_service.simple_schedule_mode(user["id"], payload.daily_count, payload.hours)
    return result


class IntervalScheduleRequest(BaseModel):
    interval_hours: float
    start_at_local: Optional[str] = None  # ISO format, timezone belgisiz (local vaqt sifatida talqin qilinadi)


@router.post("/interval-schedule")
def interval_schedule(payload: IntervalScheduleRequest, user: dict = Depends(get_current_user)):
    """
    Oddiy rejim: 'har N soatda bittadan qo'y'. Joriy foydalanuvchining barcha draft
    holatidagi shortslarini ketma-ket, bir-biridan interval_hours soat farq bilan
    avtomatik rejalashtiradi.
    """
    if payload.interval_hours <= 0:
        raise HTTPException(400, "interval_hours musbat son bo'lishi kerak")

    start_at = None
    if payload.start_at_local:
        try:
            start_at = datetime.fromisoformat(payload.start_at_local)
        except ValueError:
            raise HTTPException(400, "Noto'g'ri sana formati")

    result = scheduler_service.interval_schedule_drafts(user["id"], payload.interval_hours, start_at=start_at)
    return result


@router.get("/timezone")
def get_timezone(user: dict = Depends(get_current_user)):
    return {"timezone": scheduler_service.get_timezone_name(user["id"])}


class TimezonePayload(BaseModel):
    timezone: str


@router.post("/timezone")
def set_timezone(payload: TimezonePayload, user: dict = Depends(get_current_user)):
    try:
        ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(400, "Noto'g'ri timezone nomi")
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO settings (user_id, `key`, value) VALUES (?, 'timezone', ?) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (user["id"], payload.timezone),
        )
    return {"success": True}
