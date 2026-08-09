"""
/api/youtube — Client Secret yuklash/o'chirish, OAuth flow, akkaunt holati, playlistlar.
Har bir foydalanuvchi o'zining alohida YouTube kanaliga ulanadi.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..services import youtube_service
from ..auth import get_current_user
from ..utils.logger import log

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


@router.post("/client-secret")
async def upload_client_secret(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.filename.endswith(".json"):
        raise HTTPException(400, "Fayl .json formatida bo'lishi kerak")
    content = await file.read()
    result = youtube_service.save_client_secret(user["id"], content)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.delete("/client-secret")
def delete_client_secret(user: dict = Depends(get_current_user)):
    youtube_service.delete_client_secret(user["id"])
    return {"success": True}


@router.get("/account")
def get_account(user: dict = Depends(get_current_user)):
    return youtube_service.get_connected_account(user["id"])


@router.post("/disconnect")
def disconnect(user: dict = Depends(get_current_user)):
    youtube_service.disconnect_account(user["id"])
    return {"success": True}


@router.get("/oauth/start")
def oauth_start(user: dict = Depends(get_current_user)):
    result = youtube_service.get_authorization_url(user["id"])
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.get("/oauth/callback")
def oauth_callback(code: str, state: str = None):
    # Eslatma: bu endpoint Google tomonidan chaqiriladi, cookie sessiyasi bo'lmasligi
    # mumkin — shuning uchun qaysi foydalanuvchi ulanayotgani 'state' orqali aniqlanadi
    # (youtube_service.get_authorization_url state'ni foydalanuvchiga bog'lab saqlagan edi).
    result = youtube_service.handle_oauth_callback(code, state)
    if result["success"]:
        return RedirectResponse(url="/settings.html?youtube_connected=1")
    return RedirectResponse(url=f"/settings.html?youtube_error={result.get('message', 'error')}")


@router.get("/playlists")
def get_playlists(user: dict = Depends(get_current_user)):
    return youtube_service.get_my_playlists(user["id"])


@router.get("/categories")
def get_categories(user: dict = Depends(get_current_user)):
    return youtube_service.YOUTUBE_CATEGORIES
