"""Password hashing, JWT session tokens, and credential encryption helpers."""
from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jose import JWTError, jwt

from app.core.config import settings

_ph = PasswordHasher()
_JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SESSION_SECRET, algorithm=_JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SESSION_SECRET, algorithms=[_JWT_ALG])
    except JWTError:
        return None


def _derive_aead_key() -> bytes:
    """Derive a stable 32-byte AES-GCM key from MASTER_SECRET via HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"jsp-credential-encryption-v1",
        info=b"ApiCredential.encrypted_secret",
    )
    return hkdf.derive(settings.MASTER_SECRET.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret with AES-256-GCM. Returns base64(nonce || ciphertext)."""
    key = _derive_aead_key()
    aead = AESGCM(key)
    nonce = os.urandom(12)
    ct = aead.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_secret(blob: str) -> str:
    key = _derive_aead_key()
    raw = base64.b64decode(blob)
    nonce, ct = raw[:12], raw[12:]
    aead = AESGCM(key)
    return aead.decrypt(nonce, ct, None).decode("utf-8")
