"""
Oddiy (parolsiz) ko'p-foydalanuvchi autentifikatsiyasi.

Har bir foydalanuvchi ro'yxatdan ismini tanlab "kiradi" — parol talab qilinmaydi.
Kirishda tasodifiy sessiya tokeni yaratiladi va `sessions` jadvalida saqlanadi,
brauzerga esa HttpOnly cookie sifatida beriladi. Har bir keyingi so'rovda shu
cookie orqali `get_current_user` joriy foydalanuvchini aniqlaydi va barcha
FastAPI router'lari shu user_id bo'yicha ma'lumotlarni filtrlaydi — shu bilan
har bir kishi faqat o'z videolari/sozlamalarini/YouTube kanalini ko'radi.
"""
import secrets
from fastapi import Cookie, HTTPException, Response

from .database import get_cursor

SESSION_COOKIE_NAME = "vss_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 90  # 90 kun


def list_users() -> list:
    with get_cursor() as cur:
        cur.execute("SELECT id, name FROM users ORDER BY id ASC")
        return cur.fetchall()


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id)
        )
    return token


def destroy_session(token: str):
    if not token:
        return
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def get_user_id_from_token(token: str):
    if not token:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        )
        row = cur.fetchone()
    return row


def get_current_user(vss_session: str = Cookie(default=None)) -> dict:
    """
    FastAPI dependency: joriy foydalanuvchini cookie orqali aniqlaydi.
    Sessiya topilmasa 401 qaytaradi — frontend buni login sahifasiga
    yo'naltirish signali sifatida ishlatadi.
    """
    row = get_user_id_from_token(vss_session)
    if not row:
        raise HTTPException(401, "Kirish talab qilinadi")
    return {"id": row["id"], "name": row["name"]}
