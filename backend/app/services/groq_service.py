"""
Groq API bilan integratsiya:
  1. Whisper transkripsiya (audio -> matn) — videoning haqiqiy mazmunini o'qish uchun.
  2. Video mazmuni tahlili — transkript asosida mavzu, til, kategoriya, kalit so'zlar,
     viral tavsiyalar.
  3. SEO metadata generatsiya (Title/Description/Hashtags/Keywords) — transkript
     kontekstidan foydalanib, prompt_templates jadvalidagi shablon asosida.

Groq o'chirilgan/sozlanmagan bo'lsa, dastur to'liq ishlayveradi — bu funksiyalar
shunchaki ishlatilmaydi (Default Title/Description sozlamalari qo'llaniladi).
"""
import json
import tempfile
from pathlib import Path

import httpx

from ..database import get_cursor
from ..utils.crypto import decrypt_text
from ..utils.logger import log
from ..config import TEMP_DIR

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"
GROQ_WHISPER_MODEL = "whisper-large-v3"


def get_groq_key(user_id: int) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM api_keys WHERE user_id = ? AND provider = 'groq'", (user_id,))
        row = cur.fetchone()
    if not row or not row.get("enabled") or not row.get("encrypted_key"):
        return ""
    return decrypt_text(row["encrypted_key"])


def is_groq_enabled(user_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("SELECT enabled FROM api_keys WHERE user_id = ? AND provider = 'groq'", (user_id,))
        row = cur.fetchone()
    return bool(row and row.get("enabled"))


def test_groq_connection(api_key: str) -> dict:
    try:
        resp = httpx.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_CHAT_MODEL,
                  "messages": [{"role": "user", "content": "Salom, bu test xabari. Faqat 'OK' deb javob ber."}],
                  "max_tokens": 10},
            timeout=20,
        )
        if resp.status_code == 200:
            return {"success": True, "message": "Groq API kaliti ishlayapti."}
        return {"success": False, "message": f"Xato: HTTP {resp.status_code} - {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "message": f"Ulanishda xato: {str(e)}"}


# ==================== 1. TRANSKRIPSIYA ====================

def transcribe_video(api_key: str, video_path: str) -> dict:
    """
    Video fayldan audio ajratib, Groq Whisper orqali matnga aylantiradi.
    Qaytadi: {"success": True, "text": "...", "language": "uz"} yoki {"success": False, "message": "..."}
    """
    from ..services import ffmpeg_service

    audio_path = TEMP_DIR / f"ai_audio_{Path(video_path).stem}.mp3"
    try:
        ffmpeg_service.extract_audio_for_ai(video_path, str(audio_path))
    except Exception as e:
        return {"success": False, "message": f"Video audiosi topilmadi yoki ajratib bo'lmadi: {e}"}

    if not audio_path.exists() or audio_path.stat().st_size < 500:
        audio_path.unlink(missing_ok=True)
        return {"success": False, "message": "Videoda audio kanal topilmadi."}

    try:
        with open(audio_path, "rb") as f:
            resp = httpx.post(
                GROQ_AUDIO_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, f, "audio/mpeg")},
                data={"model": GROQ_WHISPER_MODEL, "response_format": "verbose_json"},
                timeout=120,
            )
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("text") or "").strip()
        language = data.get("language") or ""
        if not text:
            return {"success": False, "message": "Audio matnga aylantirilmadi (jim video bo'lishi mumkin)."}
        return {"success": True, "text": text, "language": language}
    except Exception as e:
        log(f"Groq transkripsiya xatosi: {e}", "error", "groq_service")
        return {"success": False, "message": str(e)}
    finally:
        audio_path.unlink(missing_ok=True)


# ==================== 2. VIDEO MAZMUNI TAHLILI ====================

def _extract_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    return json.loads(content)


def analyze_video_content(user_id: int, short_id: int, force: bool = False) -> dict:
    """
    Short uchun to'liq AI tahlil: transkripsiya (agar keshda bo'lmasa) + mavzu/til/
    kategoriya/kalit so'zlar/viral tavsiyalar aniqlash. Natija 'shorts' jadvalida
    keshlanadi, shu bilan keyingi "AI Generate" chaqiruvlari qayta transkripsiya
    qilmaydi (tezroq va API chaqiruvlarini tejaydi). Foydalanuvchining shaxsiy
    Groq API kaliti ishlatiladi.
    """
    with get_cursor() as cur:
        cur.execute("SELECT * FROM shorts WHERE id = ? AND user_id = ?", (short_id, user_id))
        row = cur.fetchone()
    if not row:
        return {"success": False, "message": "Video topilmadi"}
    if not row.get("file_path") or not Path(row["file_path"]).exists():
        return {"success": False, "message": "Video fayl diskda topilmadi"}

    api_key = get_groq_key(user_id)
    if not api_key:
        return {"success": False, "message": "Groq API kaliti sozlanmagan yoki o'chirilgan."}

    transcript = row.get("transcript") or ""
    detected_language = row.get("ai_language") or ""

    if force or not transcript:
        t = transcribe_video(api_key, row["file_path"])
        if not t.get("success"):
            return t
        transcript = t["text"]
        detected_language = t.get("language") or detected_language

    prompt = f"""Sen video kontent tahlilchisisan. Quyidagi video audiosining transkripti berilgan.
Shu transkript asosida videoni tahlil qil.

Transkript:
---
{transcript[:6000]}
---

Javobni FAQAT quyidagi JSON formatida qaytar, boshqa hech qanday matn qo'shma:
{{
  "topic": "videoning asosiy mavzusi, 1 qisqa jumla",
  "language": "video tilining ISO kodi yoki nomi (masalan: uz, ru, en)",
  "category": "eng mos YouTube kategoriyasi nomi (masalan: Ta'lim, Ko'ngilochar, Sport, Musiqa)",
  "keywords": ["kalit so'z 1", "kalit so'z 2", "kalit so'z 3", "kalit so'z 4", "kalit so'z 5"],
  "viral_tips": ["viral bo'lishi uchun aniq tavsiya 1", "tavsiya 2", "tavsiya 3"]
}}"""

    try:
        resp = httpx.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_CHAT_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.5, "max_tokens": 700, "response_format": {"type": "json_object"}},
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)

        topic = data.get("topic", "")
        language = data.get("language", detected_language)
        category = data.get("category", "")
        keywords = ", ".join(data.get("keywords", []))
        viral_tips = "\n".join(f"• {t}" for t in data.get("viral_tips", []))

        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET transcript=?, ai_topic=?, ai_language=?, ai_category=?, "
                "ai_keywords=?, ai_viral_tips=?, ai_analyzed_at=NOW() WHERE id=?",
                (transcript, topic, language, category, keywords, viral_tips, short_id),
            )

        log(f"Video #{short_id} uchun AI tahlil yakunlandi", "success", "groq_service", user_id=user_id)
        return {
            "success": True, "transcript": transcript, "topic": topic, "language": language,
            "category": category, "keywords": keywords, "viral_tips": viral_tips,
        }
    except Exception as e:
        log(f"Groq video tahlilida xato: {e}", "error", "groq_service", user_id=user_id)
        return {"success": False, "message": str(e)}


# ==================== 3. SEO METADATA (TITLE/DESCRIPTION) ====================

def _get_active_prompt_template(user_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM prompt_templates WHERE user_id = ? AND is_active = 1 LIMIT 1", (user_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM prompt_templates WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,))
            row = cur.fetchone()
    return row or {}


def _build_metadata_prompt(template: dict, context_summary: str) -> str:
    emoji_instruction = "Emoji ishlatishing mumkin va tavsiya etiladi." if template.get("use_emoji") else "Emoji ishlatmang."
    banned = template.get("banned_words", "")
    banned_instruction = f"Quyidagi so'zlarni HECH QACHON ishlatmang: {banned}." if banned else ""
    keywords = template.get("keywords", "")
    keywords_instruction = f"Quyidagi kalit so'zlarga alohida urg'u bering: {keywords}." if keywords else ""

    return f"""Sen professional YouTube SEO strategisan.
Auditoriya: {template.get('audience', 'Umumiy')}
Til: {template.get('language', 'uz')}
Uslub/Ohang: {template.get('tone', 'energetic')}
SEO fokus: {template.get('seo_focus', '')}
{keywords_instruction}
{banned_instruction}
{emoji_instruction}
Call-to-action jumlasi (description oxirida ishlatilsin): {template.get('cta_text', '')}
Qo'shimcha ko'rsatmalar: {template.get('custom_instructions', '')}

Quyidagi video mazmuni (audio transkripti asosida tahlil qilingan) uchun SEO'ga
mos Title va Description yarat. Nom va tavsif videoning HAQIQIY mazmuniga mos
bo'lishi shart — umumiy/generik bo'lmasin.
---
{context_summary}
---

Javobni FAQAT quyidagi JSON formatida qaytar, boshqa hech qanday matn qo'shma:
{{
  "title": "diqqat tortuvchi, SEO'ga mos sarlavha, {template.get('title_max_length', 100)} belgidan oshmasin",
  "description": "video mazmuniga mos, SEO optimallashtirilgan tavsif, call-to-action bilan",
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
  "keywords": ["kalit so'z 1", "kalit so'z 2", "kalit so'z 3"]
}}"""


def generate_metadata_for_short(user_id: int, short_id: int, extra_context: str = "") -> dict:
    """
    Short uchun Title/Description/Hashtags/Keywords generatsiya qiladi.
    Agar video hali AI tahlil qilinmagan bo'lsa, avval transkripsiya+tahlilni ishga
    tushiradi (bir martalik, keyingi chaqiruvlar keshdan foydalanadi).
    """
    api_key = get_groq_key(user_id)
    if not api_key:
        return {"success": False, "message": "Groq API kaliti sozlanmagan yoki o'chirilgan."}

    with get_cursor() as cur:
        cur.execute("SELECT * FROM shorts WHERE id = ? AND user_id = ?", (short_id, user_id))
        row = cur.fetchone()
    if not row:
        return {"success": False, "message": "Video topilmadi"}

    transcript = row.get("transcript")
    topic = row.get("ai_topic")
    if not transcript:
        analysis = analyze_video_content(user_id, short_id)
        if not analysis.get("success"):
            return analysis
        transcript = analysis["transcript"]
        topic = analysis["topic"]

    context_summary = f"Video mavzusi: {topic or 'noma’lum'}.\nTranskript: {transcript[:4000]}"
    if extra_context:
        context_summary += f"\nQo'shimcha kontekst: {extra_context}"

    template = _get_active_prompt_template(user_id)
    prompt = _build_metadata_prompt(template, context_summary)

    try:
        resp = httpx.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_CHAT_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.8, "max_tokens": 600, "response_format": {"type": "json_object"}},
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)

        title = data.get("title", "")[: template.get("title_max_length", 100)]
        description = data.get("description", "")
        hashtags = " ".join(data.get("hashtags", []))
        keywords_str = ", ".join(data.get("keywords", []))

        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE shorts SET title=?, description=?, hashtags=?, keywords=? WHERE id=?",
                (title, description, hashtags, keywords_str, short_id),
            )

        log(f"Short #{short_id} uchun metadata generatsiya qilindi", "success", "groq_service", user_id=user_id)
        return {"success": True, "title": title, "description": description,
                "hashtags": hashtags, "keywords": keywords_str}
    except Exception as e:
        log(f"Groq metadata generatsiyasida xato: {e}", "error", "groq_service", user_id=user_id)
        return {"success": False, "message": str(e)}
