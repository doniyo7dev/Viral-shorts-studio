#!/data/data/com.termux/files/usr/bin/bash
# ===================== Viral Shorts Studio — Termux o'rnatish skripti =====================
set -e

echo "=================================================="
echo " Viral Shorts Studio — Termux o'rnatish"
echo "=================================================="

echo "[1/5] Termux paketlarini yangilash..."
pkg update -y && pkg upgrade -y

echo "[2/5] Kerakli tizim paketlarini o'rnatish (python, ffmpeg)..."
pkg install -y python python-pip ffmpeg

echo "[3/5] Python virtual muhit yaratish..."
cd "$(dirname "$0")"
python -m venv venv
source venv/bin/activate

echo "[4/5] Python kutubxonalarini o'rnatish (bu biroz vaqt olishi mumkin)..."
pip install --upgrade pip wheel setuptools
pip install -r backend/requirements.txt

echo "[5/5] Storage papkalarini tayyorlash..."
mkdir -p backend/storage/{projects,shorts,thumbnails,temp,uploads,watermarks,youtube_secrets}

echo ""
echo "=================================================="
echo " O'rnatish yakunlandi!"
echo " Ishga tushirish uchun: ./start.sh"
echo " Yoki: source venv/bin/activate && cd backend && python main.py"
echo "=================================================="
