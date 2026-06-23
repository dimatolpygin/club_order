"""Реферальная программа для бань (этап 17): чистые хелперы.

Бизнес-логика без БД/сети — удобно покрыть smoke-тестом:
  · генерация/разбор реф-кода и deep-link `start`-payload;
  · правила квалификации новичка вынесены в repo/handlers (нужна БД).

Параметры (deep-link, формат кода) подобраны под ограничения Telegram: payload
команды `/start` — до 64 символов из [A-Za-z0-9_-].
"""
from __future__ import annotations

import secrets
import string

# Префикс реф-payload в deep-link: `https://t.me/<bot>?start=ref_<code>`.
REF_PREFIX = "ref_"

# Алфавит кода — без похожих символов (0/O, 1/l) для устной передачи.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


def new_code() -> str:
    """Случайный реф-код (уникальность обеспечивает БД — повтор перегенерируем)."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def start_payload(code: str) -> str:
    """payload для deep-link `/start` по реф-коду."""
    return f"{REF_PREFIX}{code}"


def deep_link(bot_username: str, code: str) -> str:
    """Полная реф-ссылка для пользователя."""
    return f"https://t.me/{bot_username}?start={start_payload(code)}"


def parse_start_payload(payload: str | None) -> str | None:
    """Извлекает реф-код из `start`-payload (`ref_<code>`). None — payload не реферальный.

    Код нормализуем к верхнему регистру и проверяем по алфавиту — мусор отсекаем.
    """
    if not payload or not payload.startswith(REF_PREFIX):
        return None
    code = payload[len(REF_PREFIX):].strip().upper()
    if not code:
        return None
    allowed = set(_CODE_ALPHABET) | set(string.ascii_uppercase) | set(string.digits)
    if any(ch not in allowed for ch in code):
        return None
    return code
