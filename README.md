# Viral Shorts Studio

Termux uchun professional lokal web-ilova — uzun videolardan avtomatik ravishda YouTube Shorts yaratish, tahrirlash, rejalashtirish va yuklash.

**AI'siz 100% ishlaydi.** Scene detection, motion detection va audio peak detection orqali eng qiziqarli qismlarni avtomatik topadi (faqat ffmpeg va Python standart kutubxonasi asosida — OpenCV/NumPy shart emas). Groq API — faqat ixtiyoriy, metadata (title/description/hashtags) generatsiyasi uchun.

---

## Talablar

- Termux (Android)
- Python 3.10+
- FFmpeg (audio/video kodek qo'llab-quvvatlash bilan, `libass` subtitr uchun tavsiya etiladi)
- ~500MB bo'sh joy (kutubxonalar uchun) + video fayllar uchun qo'shimcha joy

---

## O'rnatish

```bash
# Loyiha papkasiga o'ting
cd viral-shorts-studio

# Storage uchun ruxsat (agar kerak bo'lsa)
termux-setup-storage

# O'rnatish skriptini ishga tushiring
chmod +x install.sh start.sh
./install.sh
```

`install.sh` avtomatik ravishda:
1. Termux paketlarini yangilaydi
2. `python`, `ffmpeg`, `clang`, `cmake` va boshqa kerakli tizim paketlarini o'rnatadi
3. Python virtual muhit (`venv`) yaratadi
4. `backend/requirements.txt` dagi barcha Python kutubxonalarni o'rnatadi (FastAPI, OpenCV, PySceneDetect, Google API kutubxonalari va h.k.)
5. `backend/storage/` ostida kerakli papkalarni yaratadi

O'rnatish 10-20 daqiqa vaqt olishi mumkin (ayniqsa OpenCV va PySceneDetect compile bo'lishi sabab).

---

## Ishga tushirish

```bash
./start.sh
```

Yoki qo'lda:

```bash
source venv/bin/activate
cd backend
python main.py
```

Server `http://localhost:8000` manzilida ishga tushadi. Telefon brauzerida shu manzilni oching.

---

## Google Cloud Console — YouTube OAuth sozlash

YouTube'ga avtomatik yuklash uchun Google Cloud Console'da OAuth 2.0 Client ID yaratishingiz kerak:

1. [Google Cloud Console](https://console.cloud.google.com/) ga kiring va yangi loyiha yarating (yoki mavjudini tanlang).
2. **APIs & Services → Library** bo'limiga o'ting, **YouTube Data API v3** ni qidirib yoqing.
3. **APIs & Services → OAuth consent screen** bo'limida:
   - User Type: **External** ni tanlang (agar Google Workspace hisobingiz bo'lmasa)
   - Ilova nomi, qo'llab-quvvatlash email va h.k. ni to'ldiring
   - Scopes bo'limida `.../auth/youtube.upload`, `.../auth/youtube.readonly`, `.../auth/youtube.force-ssl` larni qo'shing
   - Test Users bo'limiga o'z Google hisobingizni qo'shing (ilova "Testing" holatida bo'lsa)
4. **APIs & Services → Credentials → Create Credentials → OAuth Client ID** ni tanlang:
   - Application type: **Web application**
   - Authorized redirect URIs ga qo'shing: `http://localhost:8000/api/youtube/oauth/callback`
5. Yaratilgan Client ID uchun **Download JSON** tugmasini bosing — bu `client_secret.json` fayli.
6. Ilovada **Settings → YouTube** bo'limiga kirib, shu faylni yuklang, so'ng **Google OAuth orqali ulanish** tugmasini bosing.

> **Eslatma:** Agar Termux'dan boshqa qurilmada (masalan kompyuterda) brauzer orqali OAuth flow'ni yakunlamoqchi bo'lsangiz, telefon va kompyuter bir xil tarmoqda bo'lishi va `localhost` o'rniga telefonning lokal IP manzilidan foydalanishingiz, hamda shu IP manzilni Google Cloud Console'dagi Authorized redirect URIs ro'yxatiga ham qo'shishingiz kerak bo'ladi.

---

## Ishlatish bo'yicha qisqacha yo'riqnoma

### 1. Video yuklash va Shorts yaratish
**Projects** sahifasida "Yangi Video" tugmasi orqali uzun videoni yuklang. Yuklangandan so'ng **"Tahlil qilish"** tugmasini bosing — tizim avtomatik ravishda:
- Sahna almashinuvlarini (scene detection)
- Harakat intensivligini (motion detection)
- Ovoz balandligi cho'qqilarini (audio peak detection)

tahlil qilib, eng qiziqarli 15-60 soniyalik segmentlarni topadi va ularni avtomatik 9:16 formatga o'tkazib eksport qiladi.

### 2. Shorts'ni tahrirlash
Har bir Shorts kartasida **"Tahrirlash"** tugmasi orqali: title, description, hashtags, keywords, playlist, category, visibility, crop rejimi, subtitr va watermark sozlanadi.

### 3. Metadata avtomatik generatsiyasi (ixtiyoriy)
**Settings → API Management** bo'limida Groq API kalitini kiritsangiz, Shorts tahrirlash oynasida **"Groq bilan avtomatik generatsiya"** tugmasi orqali title/description/hashtags/keywords avtomatik yaratiladi — **Prompts** sahifasida sozlagan shablon asosida.

### 4. Prompt shablonlarini sozlash
**Prompts** sahifasida auditoriya, til, uslub, SEO fokus, CTA, emoji, majburiy/taqiqlangan so'zlar kabi parametrlarni o'zingiz sozlab, bir nechta shablon saqlashingiz mumkin.

### 5. YouTube'ga ulanish va yuklash
**Settings → YouTube** bo'limida OAuth orqali ulaning. Shundan so'ng Calendar yoki Shorts oynasida belgilangan vaqtga yetganda tizim avtomatik ravishda videoni yuklaydi.

### 6. Calendar Scheduler
**Calendar** sahifasida Day/Week/Month ko'rinishlarida Shorts'larni ko'rish, drag & drop orqali boshqa vaqtga ko'chirish mumkin. **Auto Schedule** tugmasi orqali:
- Vaqt kataklarini (masalan 09:00, 13:00, 18:00, 21:00) sozlang
- "Kuniga nechta video" sonini kiriting
- **"Draft Shorts'larni Avtomatik Joylashtirish"** tugmasini bosing — barcha "draft" holatidagi Shorts navbat bilan bo'sh kataklarga joylashadi

---

## Loyiha strukturasi

```
viral-shorts-studio/
├── backend/
│   ├── app/
│   │   ├── config.py           # Barcha yo'llar va sozlamalar
│   │   ├── database.py         # SQLite schema va ulanish
│   │   ├── routers/            # FastAPI endpointlar
│   │   ├── services/           # Biznes-mantiq (FFmpeg, detection, YouTube, Groq...)
│   │   └── utils/               # Shifrlash, loglash
│   ├── storage/                 # SQLite baza + barcha video/rasm fayllar (runtime'da yaratiladi)
│   ├── main.py                  # Kirish nuqtasi
│   └── requirements.txt
├── frontend/
│   ├── index.html               # Dashboard
│   ├── pages/                   # Projects, Settings, Prompts, Calendar
│   ├── css/style.css            # Glassmorphism dizayn
│   └── js/                      # API client va umumiy utility
├── install.sh
└── start.sh
```

---

## Ma'lumotlar xavfsizligi

- API kaliti (Groq) va YouTube OAuth tokenlari **Fernet (AES) shifrlash** orqali SQLite bazasida saqlanadi.
- Shifrlash kaliti birinchi ishga tushirishda avtomatik generatsiya qilinib, `backend/storage/.secret.key` fayliga saqlanadi (bu faylni hech kimga bermang va backup qilib qo'ying — yo'qolsa, saqlangan kalitlar qayta shifrini ochib bo'lmaydi).
- Barcha ma'lumotlar to'liq lokal — hech qanday tashqi serverga yuborilmaydi (YouTube va Groq API so'rovlaridan tashqari, ular ham faqat siz ruxsat bergan holatda ishlaydi).

---

## Muammolarni bartaraf etish

**FFmpeg subtitr ishlamayapti:** Termux FFmpeg paketi `libass` bilan kelishi kerak. `ffmpeg -filters | grep subtitles` orqali tekshiring. Agar yo'q bo'lsa, `pkg install ffmpeg` ni qayta bajaring yoki `libass` alohida o'rnating.

**Video tahlili juda sekin:** Uzun (30+ daqiqa) videolar uchun motion detection ancha vaqt olishi mumkin. `backend/app/config.py` dagi `MOTION_SAMPLE_FPS` qiymatini kamaytiring (masalan 1) tezlashtirish uchun.

**YouTube yuklash xatosi:** Client Secret to'g'ri yuklanganligini, OAuth Redirect URI Google Cloud Console'da to'g'ri ko'rsatilganligini va akkauntingiz "Test users" ro'yxatida (agar ilova "Testing" holatida bo'lsa) borligini tekshiring.
