"""Рантайм-настройки, редактируемые из админки на лету (этап 8).

Сейчас здесь живут параметры напоминаний (этап 6): единица и пороги. Значения
хранятся в таблице bot_settings строками; если ключа нет — берётся дефолт из
`.env` (config.settings). Джоб напоминаний читает их при каждом проходе, поэтому
правка из админки применяется без рестарта. Частота прогона джоба
(reminder_check_interval_min) остаётся в `.env` — это инфраструктурный параметр.
"""
from __future__ import annotations

import asyncpg

from .. import repo
from ..config import settings

# Ключи настроек напоминаний в bot_settings.
KEY_UNIT = "reminder_unit"
KEY_EARLY = "reminder_early_offset"
KEY_SOON = "reminder_soon_offset"
KEY_LAST = "reminder_last_offset"

# Ссылка на аккаунт поддержки (кнопка «Перейти» в разделе «Поддержка»).
KEY_SUPPORT_URL = "support_url"

_OFFSET_KEYS = {
    "early": (KEY_EARLY, "reminder_early_offset"),
    "soon": (KEY_SOON, "reminder_soon_offset"),
    "last": (KEY_LAST, "reminder_last_offset"),
}

VALID_UNITS = ("minute", "hour", "day", "month")


async def reminder_config(pool: asyncpg.Pool) -> dict:
    """Текущие настройки напоминаний: {'unit': str, 'offsets': {early/soon/last: int}}.

    Берёт из bot_settings, недостающее — из `.env`-дефолтов.
    """
    stored = await repo.get_settings(
        pool, [KEY_UNIT, KEY_EARLY, KEY_SOON, KEY_LAST]
    )
    unit = stored.get(KEY_UNIT) or settings.reminder_unit
    offsets: dict[str, int] = {}
    for kind, (store_key, env_attr) in _OFFSET_KEYS.items():
        raw = stored.get(store_key)
        offsets[kind] = int(raw) if raw is not None else getattr(settings, env_attr)
    return {"unit": unit, "offsets": offsets}


async def set_reminder_unit(pool: asyncpg.Pool, unit: str) -> None:
    await repo.set_setting(pool, KEY_UNIT, unit)


async def set_reminder_offset(pool: asyncpg.Pool, kind: str, value: int) -> None:
    store_key = _OFFSET_KEYS[kind][0]
    await repo.set_setting(pool, store_key, str(value))


async def support_url(pool: asyncpg.Pool) -> str:
    """Текущая ссылка поддержки: из bot_settings, иначе .env-дефолт (может быть пустой)."""
    stored = await repo.get_settings(pool, [KEY_SUPPORT_URL])
    return stored.get(KEY_SUPPORT_URL) or settings.support_url


async def set_support_url(pool: asyncpg.Pool, url: str) -> None:
    await repo.set_setting(pool, KEY_SUPPORT_URL, url)
