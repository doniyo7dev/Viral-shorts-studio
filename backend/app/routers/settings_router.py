"""
/api/settings — foydalanuvchining shaxsiy sozlamalari va /api/settings/api-keys — Groq API kaliti.
Har bir foydalanuvchi o'zining alohida settings/api_keys yozuvlariga ega.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from ..database import get_cursor
from ..auth import get_current_user
from ..utils.crypto import encrypt_text, decrypt_text
from ..utils.logger import log
from ..services.groq_service import test_groq_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_all_settings(user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute("SELECT `key`, value FROM settings WHERE user_id = ?", (user["id"],))
        return {r["key"]: r["value"] for r in cur.fetchall()}


class SettingsUpdate(BaseModel):
    settings: dict


@router.post("")
def update_settings(payload: SettingsUpdate, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        for k, v in payload.settings.items():
            cur.execute(
                "INSERT INTO settings (user_id, `key`, value) VALUES (?, ?, ?) "
                "ON DUPLICATE KEY UPDATE value = VALUES(value)",
                (user["id"], k, str(v)),
            )
    return {"success": True}


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


@router.get("/api-keys")
def get_api_keys_status(user: dict = Depends(get_current_user)):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM api_keys WHERE user_id = ?", (user["id"],))
        rows = {r["provider"]: r for r in cur.fetchall()}

    result = {}
    for provider in ("groq",):
        row = rows.get(provider)
        if row and row.get("encrypted_key"):
            decrypted = decrypt_text(row["encrypted_key"])
            result[provider] = {
                "has_key": True,
                "masked_key": _mask_key(decrypted),
                "enabled": bool(row.get("enabled")),
                "last_checked_at": str(row.get("last_checked_at")) if row.get("last_checked_at") else None,
                "last_check_status": row.get("last_check_status"),
            }
        else:
            result[provider] = {"has_key": False, "masked_key": "", "enabled": False,
                                 "last_checked_at": None, "last_check_status": "unknown"}
    return result


class ApiKeyPayload(BaseModel):
    provider: str
    api_key: str


@router.post("/api-keys")
def save_api_key(payload: ApiKeyPayload, user: dict = Depends(get_current_user)):
    if payload.provider not in ("groq",):
        raise HTTPException(400, "provider 'groq' bo'lishi kerak")

    encrypted = encrypt_text(payload.api_key)
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO api_keys (user_id, provider, encrypted_key, enabled) VALUES (?, ?, ?, 1) "
            "ON DUPLICATE KEY UPDATE encrypted_key = VALUES(encrypted_key), enabled = 1",
            (user["id"], payload.provider, encrypted),
        )
    log(f"{payload.provider} API kaliti saqlandi", "success", "settings_router", user_id=user["id"])
    return {"success": True}


class ApiKeyToggle(BaseModel):
    provider: str
    enabled: bool


@router.post("/api-keys/toggle")
def toggle_api_key(payload: ApiKeyToggle, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE api_keys SET enabled = ? WHERE user_id = ? AND provider = ?",
            (1 if payload.enabled else 0, user["id"], payload.provider),
        )
    return {"success": True}


@router.delete("/api-keys/{provider}")
def delete_api_key(provider: str, user: dict = Depends(get_current_user)):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM api_keys WHERE user_id = ? AND provider = ?", (user["id"], provider))
    return {"success": True}


class ApiKeyTest(BaseModel):
    provider: str
    api_key: Optional[str] = None


@router.post("/api-keys/test")
def test_api_key(payload: ApiKeyTest, user: dict = Depends(get_current_user)):
    api_key = payload.api_key
    if not api_key:
        with get_cursor() as cur:
            cur.execute(
                "SELECT encrypted_key FROM api_keys WHERE user_id = ? AND provider = ?",
                (user["id"], payload.provider),
            )
            row = cur.fetchone()
        if not row or not row.get("encrypted_key"):
            raise HTTPException(400, "Saqlangan kalit topilmadi")
        api_key = decrypt_text(row["encrypted_key"])

    if payload.provider == "groq":
        result = test_groq_connection(api_key)
    else:
        raise HTTPException(400, "Noma'lum provider")

    status = "ok" if result["success"] else "error"
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE api_keys SET last_checked_at = NOW(), last_check_status = ? WHERE user_id = ? AND provider = ?",
            (status, user["id"], payload.provider),
        )
    return result
