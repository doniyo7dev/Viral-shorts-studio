"""
Fernet (AES-128-CBC + HMAC) simmetrik shifrlash.
Master key birinchi ishga tushirishda avtomatik generatsiya qilinib,
storage/.secret.key fayliga saqlanadi (0600 ruxsat bilan).
"""
import os
from cryptography.fernet import Fernet
from ..config import ENCRYPTION_KEY_FILE


def _load_or_create_key() -> bytes:
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    ENCRYPTION_KEY_FILE.write_bytes(key)
    try:
        os.chmod(ENCRYPTION_KEY_FILE, 0o600)
    except Exception:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_text(plain: str) -> str:
    if plain is None:
        return ""
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""
