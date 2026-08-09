"""
Viral Shorts Studio — FastAPI asosiy kirish nuqtasi.
Ishga tushirish: python -m backend.main  (yoki backend/ papkasidan: python main.py)

Ko'p-foydalanuvchi kirish nazorati: login qilmagan foydalanuvchi HTML sahifalarga
kirmoqchi bo'lsa login.html'ga yo'naltiriladi. /media fayllar ham egalik bo'yicha
tekshiriladi — boshqa foydalanuvchining video/thumbnail havolasini bilib olsa ham
ochib bo'lmaydi.
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db, get_cursor
from app.config import HOST, PORT, STORAGE_DIR
from app.auth import get_user_id_from_token
from app.utils.logger import log
from app.services.upload_worker import scheduler_tick_loop

from app.routers import (
    auth_router,
    shorts_router,
    settings_router,
    youtube_router,
    prompts_router,
    calendar_router,
    dashboard_router,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log("Viral Shorts Studio ishga tushdi", "success", "main")
    asyncio.create_task(scheduler_tick_loop())
    yield


app = FastAPI(title="Viral Shorts Studio", version="1.0.0", lifespan=lifespan)

# Eslatma: CORS ilgari "*" bilan ochiq edi. Endi cookie-asosidagi sessiya
# ishlatilgani uchun keng CORS xavfli — front va backend bir xil origin'da
# ishlaganligi sababli CORSMiddleware butunlay olib tashlandi.

app.include_router(auth_router.router)
app.include_router(shorts_router.router)
app.include_router(settings_router.router)
app.include_router(youtube_router.router)
app.include_router(prompts_router.router)
app.include_router(calendar_router.router)
app.include_router(dashboard_router.router)

# Frontend statik fayllar (CSS, JS) — bularda shaxsiy ma'lumot yo'q, ochiq qolaveradi
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")



# ==================== MEDIA FAYLLAR (video/thumbnail) — egalik tekshiruvi bilan ====================

@app.get("/media/{subpath:path}")
def serve_media(subpath: str, vss_session: str = Cookie(default=None)):
    user = get_user_id_from_token(vss_session)
    if not user:
        return RedirectResponse(url="/login.html")

    file_path = (STORAGE_DIR / subpath).resolve()
    if not str(file_path).startswith(str(STORAGE_DIR.resolve())) or not file_path.exists():
        return RedirectResponse(url="/login.html", status_code=404)

    # Fayl joriy foydalanuvchiga tegishli shorts yozuvida (file_path yoki
    # thumbnail_path sifatida) ko'rsatilgan bo'lishi shart.
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM shorts WHERE user_id = ? AND (file_path LIKE ? OR thumbnail_path LIKE ?) LIMIT 1",
            (user["id"], f"%{file_path.name}", f"%{file_path.name}"),
        )
        owned = cur.fetchone()
    if not owned:
        return RedirectResponse(url="/login.html", status_code=404)

    return FileResponse(str(file_path))


# ==================== HTML SAHIFALAR — login talab qilinadi ====================

PUBLIC_PAGES = {"login"}


@app.get("/")
def serve_index(vss_session: str = Cookie(default=None)):
    user = get_user_id_from_token(vss_session)
    if not user:
        return RedirectResponse(url="/login.html")
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/{page_name}.html")
def serve_page(page_name: str, vss_session: str = Cookie(default=None)):
    if page_name not in PUBLIC_PAGES:
        user = get_user_id_from_token(vss_session)
        if not user:
            return RedirectResponse(url="/login.html")

    page_path = FRONTEND_DIR / "pages" / f"{page_name}.html"
    if page_path.exists():
        return FileResponse(str(page_path))
    root_page = FRONTEND_DIR / f"{page_name}.html"
    if root_page.exists():
        return FileResponse(str(root_page))
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
