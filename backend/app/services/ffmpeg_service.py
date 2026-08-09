"""
FFmpeg/FFprobe bilan ishlaydigan barcha video operatsiyalari:
metadata olish, trim, smart-crop 9:16, merge, subtitle yozish, watermark qo'yish,
thumbnail generatsiya qilish va final export.
Barcha subprocess chaqiruvlari xatolikni to'liq log bilan ushlaydi.
"""
import json
import subprocess
import shlex
from pathlib import Path
from typing import Optional

from ..config import FFMPEG_BIN, FFPROBE_BIN, DEFAULT_OUTPUT_WIDTH, DEFAULT_OUTPUT_HEIGHT
from ..utils.logger import log


class FFmpegError(Exception):
    pass


def _run(cmd: list, source: str = "ffmpeg_service") -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr[-2000:] if result.stderr else "unknown error"
        log(f"Buyruq muvaffaqiyatsiz: {' '.join(cmd[:4])}... | {err}", "error", source)
        raise FFmpegError(err)
    return result


def probe_video(file_path: str) -> dict:
    """ffprobe orqali video haqida to'liq metadata olish."""
    cmd = [
        FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe xatosi: {result.stderr[-500:]}")

    data = json.loads(result.stdout)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    duration = float(data.get("format", {}).get("duration", 0) or 0)
    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0

    fps = 0.0
    if video_stream and video_stream.get("avg_frame_rate"):
        num, _, denom = video_stream["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(denom) if float(denom) != 0 else float(num)
        except (ValueError, ZeroDivisionError):
            fps = 0.0

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "has_audio": audio_stream is not None,
        "size_bytes": int(data.get("format", {}).get("size", 0) or 0),
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def extract_thumbnail(video_path: str, output_path: str, timestamp: float = 0.0):
    """Berilgan vaqtdagi freymni JPEG thumbnail sifatida chiqarish."""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", str(timestamp), "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(output_path),
    ]
    _run(cmd, "extract_thumbnail")


def _build_crop_filter(src_w: int, src_h: int, target_w: int, target_h: int, mode: str = "smart") -> str:
    """
    Manba videoni 9:16 (yoki boshqa target) formatiga moslashtirish uchun crop+scale filter zanjiri quradi.
    mode:
      - 'smart'/'center': markazdan crop qilib, keyin target o'lchamga scale qiladi
      - 'top': tepadan boshlab crop
      - 'blur_pad': crop qilinmaydi, aspekt saqlanadi, orqa fonga blur qilingan to'ldiruvchi qo'yiladi
    """
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h if src_h else target_ratio

    if mode == "blur_pad":
        # Fon: butun kadr blur qilib target o'lchamga cho'zamiz, ustiga original videoni proportsional joylashtiramiz
        return (
            f"[0:v]scale={target_w}:{target_h},boxblur=20:5,setsar=1[bg];"
            f"[0:v]scale={target_w}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )

    # smart / center / top -> crop qilib to'ldirish (cover)
    if src_ratio > target_ratio:
        # manba kengroq -> balandlik bo'yicha to'ldirib, kenglikni kesamiz
        new_h = src_h
        new_w = int(src_h * target_ratio)
    else:
        # manba tor/uzunroq -> kenglik bo'yicha to'ldirib, balandlikni kesamiz
        new_w = src_w
        new_h = int(src_w / target_ratio)

    new_w = new_w - (new_w % 2)
    new_h = new_h - (new_h % 2)

    if mode == "top":
        x_offset = (src_w - new_w) // 2
        y_offset = 0
    else:  # smart/center — markazdan (smart-crop uchun motion-tracking centerlash generate_shorts bosqichida hisoblanadi)
        x_offset = (src_w - new_w) // 2
        y_offset = (src_h - new_h) // 2

    x_offset = max(0, x_offset)
    y_offset = max(0, min(y_offset, src_h - new_h))

    return f"crop={new_w}:{new_h}:{x_offset}:{y_offset},scale={target_w}:{target_h},setsar=1"


def trim_and_format_clip(
    source_path: str,
    output_path: str,
    start: float,
    end: float,
    src_width: int,
    src_height: int,
    target_width: int = DEFAULT_OUTPUT_WIDTH,
    target_height: int = DEFAULT_OUTPUT_HEIGHT,
    crop_mode: str = "smart",
    center_x_ratio: Optional[float] = None,
):
    """
    Manba videodan [start, end] oralig'ini kesib, 9:16 formatga moslab eksport qiladi.
    center_x_ratio berilsa (0.0-1.0), smart-crop markazi shu nuqtaga siljitiladi
    (motion detection natijasidan olingan "diqqat markazi").
    """
    duration = max(0.1, end - start)

    if crop_mode == "smart" and center_x_ratio is not None:
        target_ratio = target_width / target_height
        src_ratio = src_width / src_height if src_height else target_ratio
        if src_ratio > target_ratio:
            new_h = src_height
            new_w = int(src_height * target_ratio)
        else:
            new_w = src_width
            new_h = int(src_width / target_ratio)
        new_w = new_w - (new_w % 2)
        new_h = new_h - (new_h % 2)
        center_px = int(src_width * center_x_ratio)
        x_offset = center_px - new_w // 2
        x_offset = max(0, min(x_offset, src_width - new_w))
        y_offset = max(0, (src_height - new_h) // 2)
        vf = f"crop={new_w}:{new_h}:{x_offset}:{y_offset},scale={target_width}:{target_height},setsar=1"
    else:
        vf = _build_crop_filter(src_width, src_height, target_width, target_height, crop_mode)

    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(start), "-i", str(source_path), "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "1",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    _run(cmd, "trim_and_format_clip")


def add_subtitle_burned(input_path: str, output_path: str, srt_path: str, font_size: int = 20):
    """SRT subtitrlarni videoga 'burn-in' qilish (doim ko'rinadigan qilib)."""
    escaped = str(srt_path).replace(":", "\\:").replace("'", "\\'")
    style = f"FontSize={font_size},PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=2,Alignment=2,MarginV=80"
    vf = f"subtitles='{escaped}':force_style='{style}'"
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "1",
        "-c:a", "copy",
        str(output_path),
    ]
    _run(cmd, "add_subtitle_burned")


def add_watermark(input_path: str, output_path: str, watermark_path: str,
                   position: str = "top_right", opacity: float = 0.8, scale_width: int = 150):
    """PNG/JPG watermarkni videoning ustiga chizish."""
    positions = {
        "top_left": "10:10",
        "top_right": "W-w-10:10",
        "bottom_left": "10:H-h-10",
        "bottom_right": "W-w-10:H-h-10",
        "center": "(W-w)/2:(H-h)/2",
    }
    overlay_pos = positions.get(position, positions["top_right"])
    filter_complex = (
        f"[1:v]scale={scale_width}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay={overlay_pos}"
    )
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path), "-i", str(watermark_path),
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "1",
        "-c:a", "copy",
        str(output_path),
    ]
    _run(cmd, "add_watermark")


def merge_clips(clip_paths: list, output_path: str):
    """Bir nechta klipni ketma-ket birlashtirish (concat demuxer usuli, re-encode bilan barqarorlik uchun)."""
    list_file = Path(output_path).parent / f"_concat_{Path(output_path).stem}.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            escaped = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "1",
        "-c:a", "aac", "-b:a", "160k",
        str(output_path),
    ]
    try:
        _run(cmd, "merge_clips")
    finally:
        list_file.unlink(missing_ok=True)


def extract_audio_for_ai(input_path: str, output_mp3: str, max_seconds: int = 600):
    """
    AI tahlil (Groq Whisper transkripsiya) uchun audio ajratib olish: kichik hajmli
    mono MP3, birinchi `max_seconds` soniya bilan cheklangan (API yuklash hajmi va
    tezlik uchun). Video audio kanalga ega bo'lmasa, ffmpeg xato beradi — chaqiruvchi
    tomon buni ushlab, "audio yo'q" holatini alohida boshqarishi kerak.
    """
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path),
        "-t", str(max_seconds),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(output_mp3),
    ]
    _run(cmd, "extract_audio_for_ai")
