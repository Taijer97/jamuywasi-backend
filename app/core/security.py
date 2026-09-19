from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import hashlib
import hmac
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from app.core.config import settings

# Argon2id: algoritmo recomendado para almacenar contraseñas/PIN.
_ph = PasswordHasher()


def _legacy_sha256(password: str) -> str:
    """Hash antiguo (SHA-256 + salt fijo). Solo se usa para verificar cuentas antiguas
    y migrarlas automáticamente a Argon2 en su siguiente inicio de sesión."""
    salt = settings.LEGACY_PASSWORD_SALT or settings.JWT_SECRET[:16]
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def is_legacy_hash(hashed_password: str) -> bool:
    return not (hashed_password or "").startswith("$argon2")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    if is_legacy_hash(hashed_password):
        return hmac.compare_digest(_legacy_sha256(plain_password), hashed_password)
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    if is_legacy_hash(hashed_password):
        return True
    try:
        return _ph.check_needs_rehash(hashed_password)
    except Exception:
        return False


def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None
