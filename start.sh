#!/data/data/com.termux/files/usr/bin/bash
# Viral Shorts Studio serverni ishga tushirish
cd "$(dirname "$0")"
source venv/bin/activate
cd backend
echo "Server ishga tushmoqda: http://localhost:8000"
echo "Brauzerda oching: http://localhost:8000"
python main.py
