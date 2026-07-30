"""Сервис тарифов: цена входа/продления и длительности для экрана выбора (этап 43).

С этапа 43 авто-ступени по числу занятых мест УБРАНЫ. Остаются две цены (₽/мес),
которые админ правит в веб-админке (хранятся в bot_settings):
  · вход      — для новичка и после перерыва (get_current_tier / entry_rate);
  · продление — для непрерывного подписчика (renewal_rate).
Регулировка стоимости для первых участников — промокодами (этап 7).

Длительности (1/3/6/12 мес и др.) кешируются в Redis и инвалидируются при правке
админом — поэтому изменения видны без рестарта. Цена за срок = ставка × число
периодов (матрица цен-за-период ступеней больше не применяется).
"""
from __future__ import annotations

import json
from decimal import Decimal

import asyncpg
from redis.asyncio import Redis

from .. import repo
from . import app_settings

_DURATIONS_KEY = "cache:durations"
# Legacy-ключи ступеней/матрицы (этапы 2–23): движок их больше не пишет, но
# invalidate() чистит их, чтобы старые записи в Redis не «всплыли».
_TIERS_KEY = "cache:tiers"
_PRICES_KEY = "cache:tier_prices"
_TTL = 300  # сек


async def _cached_active_durations(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    raw = await redis.get(_DURATIONS_KEY)
    if raw is not None:
        return json.loads(raw)
    rows = await repo.get_active_durations(pool)
    durations = [
        {"id": r["id"], "months": r["months"], "unit": r["unit"]} for r in rows
    ]
    await redis.set(_DURATIONS_KEY, json.dumps(durations), ex=_TTL)
    return durations


async def invalidate(redis: Redis) -> None:
    """Сбросить кеш длительностей (вызывать после правки админом)."""
    await redis.delete(_DURATIONS_KEY, _TIERS_KEY, _PRICES_KEY)


async def entry_rate(pool: asyncpg.Pool) -> Decimal:
    """Цена входа (₽/мес): новичок / после перерыва. 0 — если не задана."""
    return (await app_settings.subscription_prices(pool))["entry"]


async def renewal_rate(pool: asyncpg.Pool) -> Decimal:
    """Цена продления (₽/мес): непрерывный подписчик. 0 — если не задана."""
    return (await app_settings.subscription_prices(pool))["renewal"]


async def renewal_monthly_for(pool: asyncpg.Pool, sub) -> Decimal:
    """Месячная ставка продления для конкретной подписки (этап 44).

    Приоритет промокода: если за подпиской закреплена промо-цена
    (fixes_price-промокод → `price_locked=true`), продление считается по ней —
    скидка продления НЕ суммируется. Иначе — текущая цена продления; если она не
    задана (≤0), падаем на прежнюю ставку подписки, чтобы не выставить 0 ₽.
    """
    if sub["price_locked"]:
        return sub["fixed_price"]
    monthly = await renewal_rate(pool)
    if monthly <= 0:
        monthly = sub["fixed_price"]
    return monthly


async def period_price(
    pool: asyncpg.Pool, redis: Redis, tier: dict, value: int, unit: str = "month"
) -> Decimal:
    """Цена за период: ставка × число периодов (этап 43 — без матрицы ступеней)."""
    return tier["monthly_price"] * value


async def prices_for(
    pool: asyncpg.Pool, redis: Redis, tier: dict, durations: list[dict]
) -> dict[int, Decimal]:
    """Цены за набор длительностей одним проходом → {duration_id: price}."""
    return {d["id"]: tier["monthly_price"] * d["months"] for d in durations}


async def get_current_tier(pool: asyncpg.Pool, redis: Redis) -> dict | None:
    """«Ступень» входа для нового участника (этап 43 — без счёта мест).

    Ступени по местам убраны: новичок всегда платит цену ВХОДА. Возвращаем
    синтетическую ступень {id, name, monthly_price(Decimal), tier_index} с ценой
    входа; id=None (в payments/subscriptions tier_id nullable — «промо/кастом»).
    None — только если цена входа не задана (≤0): экран «мест нет» тогда страхует
    от продажи по нулю.
    """
    rate = await entry_rate(pool)
    if rate <= 0:
        return None
    return {"id": None, "name": "Клуб 11:11", "monthly_price": rate, "tier_index": 1}


async def get_active_durations(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    return await _cached_active_durations(pool, redis)
