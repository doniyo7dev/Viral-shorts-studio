"""
/api/auth — foydalanuvchilar ro'yxati, kirish (ism tanlash, parolsiz), chiqish, joriy foydalanuvchi.
"""
from fastapi import APIRouter, HTTPException, Response, Depends, Cookie
from pydantic import BaseModel

from .. import auth
from ..utils.logger import log

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/users")
def get_users():
    """Login sahifasida ko'rsatiladigan foydalanuvchilar ro'yxati (parolsiz tanlash uchun)."""
    return auth.list_users()


class LoginPayload(BaseModel):
    user_id: int


@router.post("/login")
def login(payload: LoginPayload, response: Response):
    users = {u["id"]: u["name"] for u in auth.list_users()}
    if payload.user_id not in users:
        raise HTTPException(400, "Noto'g'ri foydalanuvchi")

    token = auth.create_session(payload.user_id)
    auth.set_session_cookie(response, token)
    log(f"{users[payload.user_id]} tizimga kirdi", "info", "auth_router")
    return {"success": True, "user": {"id": payload.user_id, "name": users[payload.user_id]}}


@router.post("/logout")
def logout(response: Response, vss_session: str = Cookie(default=None)):
    auth.destroy_session(vss_session)
    auth.clear_session_cookie(response)
    return {"success": True}


@router.get("/me")
def me(user: dict = Depends(auth.get_current_user)):
    return user
