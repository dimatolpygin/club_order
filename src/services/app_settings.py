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

# Доп-администраторы, добавленные из админки (помимо ADMIN_IDS из .env).
KEY_EXTRA_ADMINS = "extra_admin_ids"

# In-memory кеш доп-админов — чтобы проверка прав (_is_admin) оставалась
# синхронной, без обращения к БД на каждое действие. Загружается при старте
# (load_extra_admins) и обновляется при add/remove. Множество tg_id.
_extra_admins: set[int] = set()

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


# ── Доп-администраторы ────────────────────────────────────────────────────────
def _parse_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    return {
        int(p) for p in raw.replace(" ", "").split(",")
        if p.lstrip("-").isdigit()
    }


async def load_extra_admins(pool: asyncpg.Pool) -> set[int]:
    """Загружает доп-админов из bot_settings в in-memory кеш. Вызывается при старте."""
    global _extra_admins
    stored = await repo.get_settings(pool, [KEY_EXTRA_ADMINS])
    _extra_admins = _parse_ids(stored.get(KEY_EXTRA_ADMINS))
    return set(_extra_admins)


def extra_admin_ids() -> set[int]:
    """Текущий кеш доп-админов (синхронно, без БД)."""
    return _extra_admins


async def _persist_extra_admins(pool: asyncpg.Pool) -> None:
    value = ",".join(str(i) for i in sorted(_extra_admins))
    await repo.set_setting(pool, KEY_EXTRA_ADMINS, value)


async def add_extra_admin(pool: asyncpg.Pool, tg_id: int) -> None:
    _extra_admins.add(tg_id)
    await _persist_extra_admins(pool)


async def remove_extra_admin(pool: asyncpg.Pool, tg_id: int) -> None:
    _extra_admins.discard(tg_id)
    await _persist_extra_admins(pool)
