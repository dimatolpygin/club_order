"""Хэширование и проверка паролей администраторов.

Используем стандартную библиотеку (pbkdf2_hmac) — без тяжёлых зависимостей вроде
bcrypt, которые требуют компиляции. Формат строки в БД:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000


def hash_password(plain: str) -> str:
    """Возвращает строку-хэш для хранения в БД."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Проверяет пароль против сохранённого хэша. Постоянное время сравнения."""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)
