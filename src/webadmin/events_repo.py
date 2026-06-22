"""Запросы к БД для раздела «Мероприятия» (события + цены билетов)."""
from __future__ import annotations

from datetime import datetime

import asyncpg

_EVENT_COLS = (
    "id, kind, title, starts_at, gender_balance, seats_total, seats_male, "
    "seats_female, show_in_advance, subscriber_discount_percent, address, "
    "rules_text, is_active, created_at"
)


async def list_events(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        f"SELECT {_EVENT_COLS} FROM events ORDER BY starts_at"
    )


async def get_event(pool: asyncpg.Pool, event_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        f"SELECT {_EVENT_COLS} FROM events WHERE id = $1", event_id
    )


async def get_prices(pool: asyncpg.Pool, event_id: int) -> dict[str, int]:
    rows = await pool.fetch(
        "SELECT ticket_type, price FROM event_ticket_prices WHERE event_id = $1",
        event_id,
    )
    return {r["ticket_type"]: r["price"] for r in rows}


async def prices_by_event(pool: asyncpg.Pool) -> dict[int, dict[str, int]]:
    """Все цены сразу, сгруппированные по событию — для списка без N+1."""
    rows = await pool.fetch(
        "SELECT event_id, ticket_type, price FROM event_ticket_prices"
    )
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["event_id"], {})[r["ticket_type"]] = r["price"]
    return out


async def create_event(pool: asyncpg.Pool, data: dict) -> int:
    return await pool.fetchval(
        """
        INSERT INTO events (
            kind, title, starts_at, gender_balance, seats_total, seats_male,
            seats_female, show_in_advance, subscriber_discount_percent,
            address, rules_text, is_active
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        RETURNING id
        """,
        data["kind"], data["title"], data["starts_at"], data["gender_balance"],
        data["seats_total"], data["seats_male"], data["seats_female"],
        data["show_in_advance"], data["subscriber_discount_percent"],
        data["address"], data["rules_text"], data["is_active"],
    )


async def update_event(pool: asyncpg.Pool, event_id: int, data: dict) -> None:
    await pool.execute(
        """
        UPDATE events SET
            kind=$2, title=$3, starts_at=$4, gender_balance=$5, seats_total=$6,
            seats_male=$7, seats_female=$8, show_in_advance=$9,
            subscriber_discount_percent=$10, address=$11, rules_text=$12, is_active=$13
        WHERE id=$1
        """,
        event_id, data["kind"], data["title"], data["starts_at"],
        data["gender_balance"], data["seats_total"], data["seats_male"],
        data["seats_female"], data["show_in_advance"],
        data["subscriber_discount_percent"], data["address"],
        data["rules_text"], data["is_active"],
    )


async def set_prices(pool: asyncpg.Pool, event_id: int, prices: dict[str, int | None]) -> None:
    """Сохраняет цены по типам билетов: значение есть → upsert, None → удалить строку."""
    async with pool.acquire() as con:
        async with con.transaction():
            for ttype, price in prices.items():
                if price is None:
                    await con.execute(
                        "DELETE FROM event_ticket_prices WHERE event_id=$1 AND ticket_type=$2",
                        event_id, ttype,
                    )
                else:
                    await con.execute(
                        """
                        INSERT INTO event_ticket_prices (event_id, ticket_type, price)
                        VALUES ($1,$2,$3)
                        ON CONFLICT (event_id, ticket_type)
                        DO UPDATE SET price = EXCLUDED.price
                        """,
                        event_id, ttype, price,
                    )


async def delete_event(pool: asyncpg.Pool, event_id: int) -> None:
    # Цены удалятся каскадом (FK ON DELETE CASCADE).
    await pool.execute("DELETE FROM events WHERE id = $1", event_id)
