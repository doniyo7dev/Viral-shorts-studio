"""
SRT subtitle fayl generatsiya qilish.
Foydalanuvchi matnni qo'lda kiritadi (yoki keyinchalik tahrirlaydi),
bu modul matnni videoning davomiyligiga mos ravishda vaqt bo'yicha segmentlarga bo'lib,
standart SRT formatga aylantiradi.
"""
import re
from pathlib import Path


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt_from_text(text: str, duration: float, output_path: str, max_chars_per_line: int = 40):
    """
    Foydalanuvchi kiritgan matnni jumlalarga bo'lib, videoning umumiy davomiyligiga
    proportsional ravishda vaqt oralig'iga taqsimlaydi va SRT fayl yaratadi.
    """
    text = text.strip()
    if not text:
        return

    # Jumlalarga ajratish (., !, ? bo'yicha), bo'lmasa vergul bo'yicha
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        sentences = [text]

    # Uzun jumlalarni max_chars ga qarab qism-qism bo'lish
    chunks = []
    for sentence in sentences:
        words = sentence.split()
        current = ""
        for w in words:
            if len(current) + len(w) + 1 <= max_chars_per_line:
                current = f"{current} {w}".strip()
            else:
                if current:
                    chunks.append(current)
                current = w
        if current:
            chunks.append(current)

    if not chunks:
        chunks = [text[:max_chars_per_line]]

    per_chunk_duration = duration / len(chunks)

    lines = []
    for i, chunk in enumerate(chunks):
        start_t = i * per_chunk_duration
        end_t = min((i + 1) * per_chunk_duration, duration)
        lines.append(str(i + 1))
        lines.append(f"{_format_srt_time(start_t)} --> {_format_srt_time(end_t)}")
        lines.append(chunk)
        lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
