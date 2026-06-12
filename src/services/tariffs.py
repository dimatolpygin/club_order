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
    durations = [{"id": r["id"], "months": r["months"]} for r in rows]
    await redis.set(_DURATIONS_KEY, json.dumps(durations), ex=_TTL)
    return durations


async def invalidate(redis: Redis) -> None:
    """Сбросить кеш тарифов/длительностей (вызывать после правки админом)."""
    await redis.delete(_TIERS_KEY, _DURATIONS_KEY)


async def get_available_tiers(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    """Активные ступени, у которых ещё есть свободные места.

    Каждый элемент: id, name, monthly_price(Decimal), seat_limit, occupied, seats_left.
    Ступень со seat_limit=NULL — безлимит. Исчерпанные места — отфильтрованы.
    """
    tiers = await _cached_active_tiers(pool, redis)
    occupancy = await repo.tier_occupancy(pool)

    available: list[dict] = []
    for t in tiers:
        occupied = occupancy.get(t["id"], 0)
        limit = t["seat_limit"]
        if limit is not None and occupied >= limit:
            continue  # места по этой ступени закончились — скрываем
        available.append(
            {
                "id": t["id"],
                "name": t["name"],
                "monthly_price": Decimal(t["monthly_price"]),
                "seat_limit": limit,
                "occupied": occupied,
                "seats_left": None if limit is None else (limit - occupied),
            }
        )
    return available


async def get_available_durations(pool: asyncpg.Pool, redis: Redis) -> list[dict]:
    return await _cached_active_durations(pool, redis)
