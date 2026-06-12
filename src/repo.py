"""Слой доступа к данным. Все таблицы — в схеме club_bot (search_path задан в db.py)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import asyncpg


async def upsert_user(
    pool: asyncpg.Pool, tg_id: int, username: str | None, first_name: str | None
) -> None:
    """Создаёт/обновляет запись пользователя при любом входящем действии."""
    await pool.execute(
        """
        INSERT INTO users(tg_id, username, first_name)
        VALUES($1, $2, $3)
        ON CONFLICT (tg_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = now()
        """,
        tg_id,
        username,
        first_name,
    )


async def set_fsm_state(pool: asyncpg.Pool, tg_id: int, state: str | None) -> None:
    """Фиксирует текущее FSM-состояние пользователя (чтобы видеть, где застрял).

    state=None означает выход из сценария.
    """
    await pool.execute(
        """
        INSERT INTO fsm_states(tg_id, state)
        VALUES($1, $2)
        ON CONFLICT (tg_id) DO UPDATE
            SET state = EXCLUDED.state,
                updated_at = now()
        """,
        tg_id,
        state,
    )


# ── Тарифы (price_tiers) ─────────────────────────────────────────────────────
async def get_all_tiers(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM price_tiers ORDER BY sort_order, id"
    )


async def get_active_tiers(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM price_tiers WHERE is_active = true ORDER BY sort_order, id"
    )


async def get_tier(pool: asyncpg.Pool, tier_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM price_tiers WHERE id = $1", tier_id)


async def update_tier(pool: asyncpg.Pool, tier_id: int, **fields) -> bool:
    """Обновляет произвольные поля ступени. Возвращает True, если строка найдена."""
    allowed = {"name", "monthly_price", "seat_limit", "sort_order", "is_active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    cols = ", ".join(f"{k} = ${i}" for i, k in enumerate(sets, start=2))
    row = await pool.fetchrow(
        f"UPDATE price_tiers SET {cols}, updated_at = now() WHERE id = $1 RETURNING id",
        tier_id,
        *sets.values(),
    )
    return row is not None


async def tier_occupancy(pool: asyncpg.Pool) -> dict[int, int]:
    """Сколько мест занято по каждой ступени = число активных подписок этой ступени."""
    rows = await pool.fetch(
        """
        SELECT tier_id, COUNT(*) AS n
        FROM subscriptions
        WHERE status = 'active' AND end_date > now() AND tier_id IS NOT NULL
        GROUP BY tier_id
        """
    )
    return {r["tier_id"]: r["n"] for r in rows}


# ── Длительности (durations) ─────────────────────────────────────────────────
async def get_all_durations(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM durations ORDER BY sort_order, months")


async def get_active_durations(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM durations WHERE is_active = true ORDER BY sort_order, months"
    )


async def get_duration(pool: asyncpg.Pool, duration_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM durations WHERE id = $1", duration_id)


async def upsert_duration(pool: asyncpg.Pool, months: int, is_active: bool = True) -> None:
    await pool.execute(
        """
        INSERT INTO durations(months, sort_order, is_active)
        VALUES($1, $1, $2)
        ON CONFLICT (months) DO UPDATE SET is_active = EXCLUDED.is_active
        """,
        months,
        is_active,
    )


async def set_duration_active(pool: asyncpg.Pool, months: int, is_active: bool) -> bool:
    row = await pool.fetchrow(
        "UPDATE durations SET is_active = $2 WHERE months = $1 RETURNING id",
        months,
        is_active,
    )
    return row is not None


# ── Подписки (subscriptions) ─────────────────────────────────────────────────
async def add_subscription(
    pool: asyncpg.Pool,
    tg_id: int,
    tier_id: int | None,
    fixed_price: Decimal | int | float,
    months: int,
    end_date: datetime,
    source: str = "payment",
    status: str = "active",
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO subscriptions(tg_id, tier_id, fixed_price, months, end_date, source, status)
        VALUES($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        tg_id,
        tier_id,
        Decimal(str(fixed_price)),
        months,
        end_date,
        source,
        status,
    )
    return row["id"]


async def get_active_subscription(pool: asyncpg.Pool, tg_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT * FROM subscriptions
        WHERE tg_id = $1 AND status = 'active' AND end_date > now()
        ORDER BY end_date DESC
        LIMIT 1
        """,
        tg_id,
    )
