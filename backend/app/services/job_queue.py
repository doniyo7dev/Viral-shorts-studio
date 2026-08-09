"""
Global video-processing navbati.

Render Free (512MB RAM, 0.1 CPU) kabi cheklangan serverlarda bir vaqtning o'zida
bir nechta og'ir ffmpeg jarayoni ishga tushsa, xotira tugab server 502 bilan yiqiladi.

Shu sabab BARCHA og'ir video operatsiyalari (tahlil, eksport, subtitr, watermark,
crop, birlashtirish) shu yerdagi BITTA ishchi (single-worker) navbat orqali,
KETMA-KET (bittalab) bajariladi — hech qachon parallel ishlamaydi.

Foydalanish: threading.Thread(target=fn, ...) o'rniga submit_job(fn, *args, **kwargs).
"""
import queue
import threading
from ..utils.logger import log

_job_queue: "queue.Queue" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _worker_loop():
    while True:
        func, args, kwargs, label = _job_queue.get()
        try:
            log(f"Navbatdagi vazifa boshlandi: {label}", "info", "job_queue")
            func(*args, **kwargs)
            log(f"Navbatdagi vazifa tugadi: {label}", "success", "job_queue")
        except Exception as e:
            log(f"Navbatdagi vazifa xatosi ({label}): {e}", "error", "job_queue")
        finally:
            _job_queue.task_done()


def _ensure_worker_started():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(target=_worker_loop, daemon=True, name="video-job-worker")
            t.start()
            _worker_started = True
            log("Video ishlov berish navbati ishga tushdi (1 ta ishchi)", "info", "job_queue")


def submit_job(func, *args, label: str = "", **kwargs):
    """
    Og'ir video vazifasini (ffmpeg orqali) navbatga qo'shadi.
    Vazifalar qo'shilgan tartibda, bittalab (ketma-ket) bajariladi.
    Chaqiruv darhol qaytadi (non-blocking) — natija kutilmaydi, xuddi Thread.start() kabi.
    """
    _ensure_worker_started()
    _job_queue.put((func, args, kwargs, label or func.__name__))


def queue_size() -> int:
    return _job_queue.qsize()
