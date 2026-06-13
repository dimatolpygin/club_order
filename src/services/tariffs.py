"""Сервис тарифов: доступные ступени и длительности для экрана выбора.

Определения ступеней/длительностей (цена, лимит, активность) кешируются в Redis
и инвалидируются при правке админом — поэтому изменения видны без рестарта.
Занятые места считаются ЖИВЫМ запросом при каждом рендере (меняются при оплатах),
поэтому в кеш не попадают.
"""
from __future__ import annotations

import json
from decimal import Decimal

import asyncpg
from redis.asyncio import Redis

from .. import repo

_TIERS_KEY = "cache:tiers"
_DURATIONS_KEY = "cache:durations"
_PRICES_KEY = "cache:tier_prices"
_TTL = 300  # сек


async def _cached_active_tiers(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    raw = await redis.get(_TIERS_KEY)
    if raw is not None:
        return json.loads(raw)
    rows = await repo.get_active_tiers(pool)
    tiers = [
        {
            "id": r["id"],
            "name": r["name"],
            "monthly_price": str(r["monthly_price"]),  # Decimal → str для JSON
            "seat_limit": r["seat_limit"],
            "sort_order": r["sort_order"],
        }
        for r in rows
    ]
    await redis.set(_TIERS_KEY, json.dumps(tiers), ex=_TTL)
    return tiers


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


def _period_key(value: int, unit: str) -> str:
    return f"{value}:{unit}"


async def _cached_tier_prices(pool: asyncpg.Pool, redis: Redis) -> dict[str, dict[str, str]]:
    """Матрица переопределений цены: {tier_id: {"значение:единица": price}} (строки для JSON)."""
    raw = await redis.get(_PRICES_KEY)
    if raw is not None:
        return json.loads(raw)
    rows = await repo.get_all_tier_prices(pool)
    matrix: dict[str, dict[str, str]] = {}
    for r in rows:
        matrix.setdefault(str(r["tier_id"]), {})[
            _period_key(r["months"], r["unit"])
        ] = str(r["price"])
    await redis.set(_PRICES_KEY, json.dumps(matrix), ex=_TTL)
    return matrix


async def invalidate(redis: Redis) -> None:
    """Сбросить кеш тарифов/длительностей/цен (вызывать после правки админом)."""
    await redis.delete(_TIERS_KEY, _DURATIONS_KEY, _PRICES_KEY)


async def period_price(
    pool: asyncpg.Pool, redis: Redis, tier: dict, value: int, unit: str = "month"
) -> Decimal:
    """Цена за период внутри ступени: переопределение из матрицы или ставка×значение.

    Для немесячных единиц (день/час/минута) админ обычно задаёт цену явно;
    fallback ставка×значение — лишь страховка, чтобы покупка не блокировалась.
    """
    matrix = await _cached_tier_prices(pool, redis)
    override = matrix.get(str(tier["id"]), {}).get(_period_key(value, unit))
    if override is not None:
        return Decimal(override)
    return tier["monthly_price"] * value


async def prices_for(
    pool: asyncpg.Pool, redis: Redis, tier: dict, durations: list[dict]
) -> dict[int, Decimal]:
    """Цены за набор длительностей одним проходом → {duration_id: price}."""
    matrix = await _cached_tier_prices(pool, redis)
    overrides = matrix.get(str(tier["id"]), {})
    result: dict[int, Decimal] = {}
    for d in durations:
        ov = overrides.get(_period_key(d["months"], d["unit"]))
        result[d["id"]] = (
            Decimal(ov) if ov is not None else tier["monthly_price"] * d["months"]
        )
    return result


async def get_current_tier(pool: asyncpg.Pool, redis: Redis) -> dict | None:
    """Текущая ценовая ступень — определяется числом уже занятых мест в клубе.

    Ступени-брекеты идут по порядку с кумулятивными лимитами:
    места 1..L1 → ступень 1, L1+1..L1+L2 → ступень 2, и т.д.
    Ступень с seat_limit=NULL («Стандарт») ловит всех сверх лимитов.
    Возвращает {id, name, monthly_price(Decimal), tier_index} или None,
    если все лимитные ступени заполнены и безлимитной нет.
    Ступени пользователю НЕ показываются — это внутренний механизм цены.
    """
    tiers = await _cached_active_tiers(pool, redis)
    if not tiers:
        return None
    taken = await repo.count_active_members(pool)

    cumulative = 0
    for idx, t in enumerate(tiers, start=1):
        limit = t["seat_limit"]
        if limit is None:
            # Безлимитная ступень — текущая для всех, кто за пределами брекетов.
            return _to_tier(t, idx)
        cumulative += limit
        if taken < cumulative:
            return _to_tier(t, idx)
    return None  # все лимитные ступени заполнены, безлимитной нет


def _to_tier(t: dict, idx: int) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "monthly_price": Decimal(t["monthly_price"]),
        "tier_index": idx,
    }


async def get_active_durations(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    return await _cached_active_durations(pool, redis)
