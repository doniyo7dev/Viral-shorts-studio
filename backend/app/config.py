"""
Viral Shorts Studio - Global Configuration
Barcha yo'llar, konstantalar va sozlamalar shu yerda markazlashtirilgan.
"""
import os
from pathlib import Path

# ---- Bazaviy yo'llar ----
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = STORAGE_DIR / "app.db"

SHORTS_DIR = STORAGE_DIR / "shorts"            # render qilingan/eksport qilingan video fayllar
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"    # videolar uchun thumbnail rasmlar
TEMP_DIR = STORAGE_DIR / "temp"                # vaqtinchalik ishlov berish fayllari (audio, srt va h.k.)
UPLOADS_DIR = STORAGE_DIR / "uploads"          # foydalanuvchi yuklagan original video fayllari
WATERMARKS_DIR = STORAGE_DIR / "watermarks"    # watermark rasm/logo fayllari
CLIENT_SECRETS_DIR = STORAGE_DIR / "youtube_secrets"

for d in [STORAGE_DIR, SHORTS_DIR, THUMBNAILS_DIR, TEMP_DIR,
          UPLOADS_DIR, WATERMARKS_DIR, CLIENT_SECRETS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---- Shifrlash uchun master key fayli (birinchi ishga tushirishda avtomatik yaratiladi) ----
ENCRYPTION_KEY_FILE = STORAGE_DIR / ".secret.key"

# ---- Chiqish o'lchami (foydalanuvchi videoni qo'lda formatlashtirish/crop tanlaganda) ----
DEFAULT_TARGET_ASPECT_RATIO = (9, 16)
DEFAULT_OUTPUT_WIDTH = 1080
DEFAULT_OUTPUT_HEIGHT = 1920

# ---- Server ----
HOST = os.environ.get("SHORTS_STUDIO_HOST", "0.0.0.0")
# Render/Heroku kabi platformalar odatda PORT environment variable orqali portni beradi.
PORT = int(os.environ.get("PORT", os.environ.get("SHORTS_STUDIO_PORT", "8000")))

# ---- Timezone ----
DEFAULT_TIMEZONE = "Asia/Tashkent"

# ---- YouTube OAuth ----
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
YOUTUBE_REDIRECT_URI = os.environ.get(
    "YOUTUBE_REDIRECT_URI", "http://localhost:8000/api/youtube/oauth/callback"
)

# ---- FFmpeg / FFprobe binary nomlari (Termux PATH ichida bo'lishi kerak) ----
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")

import os
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "300"))  # kichik/bepul serverlar uchun xavfsiz default
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
