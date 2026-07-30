"""Запросы к БД для раздела «Мероприятия» (события + цены билетов)."""
from __future__ import annotations

from datetime import datetime

import asyncpg

_EVENT_COLS = (
    "id, kind, title, starts_at, gender_balance, seats_total, seats_male, "
    "seats_female, show_in_advance, subscriber_discount_percent, address, "
    "rules_text, is_active, canceled_at, created_at"
)


async def list_events(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        f"SELECT {_EVENT_COLS} FROM events ORDER BY starts_at"
    )


def _events_filters(
    base_clause: str, search: str | None, kind: str | None, status: str | None
) -> tuple[str, list]:
    """WHERE-условие и параметры для списков мероприятий (этап 36).

    base_clause — стартовое условие времени (`starts_at >= now()` для предстоящих,
    `starts_at < now()` для прошедших). search — ILIKE по названию (частичный,
    регистронезависимо). kind — 'banya'/'retreat' (иначе все). status — 'active'
    (в боте), 'hidden' (скрыто), 'canceled' (отменено), иначе все.
    """
    clauses = [base_clause]
    params: list = []
    if kind in ("banya", "retreat"):
        params.append(kind)
        clauses.append(f"kind = ${len(params)}")
    if status == "active":
        clauses.append("is_active = true AND canceled_at IS NULL")
    elif status == "hidden":
        clauses.append("is_active = false AND canceled_at IS NULL")
    elif status == "canceled":
        clauses.append("canceled_at IS NOT NULL")
    s = (search or "").strip()
    if s:
        params.append(f"%{s}%")
        clauses.append(f"title ILIKE ${len(params)}")
    return " AND ".join(clauses), params


async def list_upcoming_events(
    pool: asyncpg.Pool, *, search: str | None = None,
    kind: str | None = None, status: str | None = None,
) -> list[asyncpg.Record]:
    """Предстоящие события под фильтры (этап 36). Без пагинации — их мало."""
    where, params = _events_filters("starts_at >= now()", search, kind, status)
    return await pool.fetch(
        f"SELECT {_EVENT_COLS} FROM events WHERE {where} ORDER BY starts_at", *params
    )


async def list_past_events(
    pool: asyncpg.Pool, *, search: str | None = None,
    kind: str | None = None, status: str | None = None,
    limit: int | None = None, offset: int = 0,
) -> list[asyncpg.Record]:
    """Прошедшие события под фильтры + пагинация (этап 36). Свежие сверху."""
    where, params = _events_filters("starts_at < now()", search, kind, status)
    tail = ""
    if limit is not None:
        params.append(limit)
        tail += f" LIMIT ${len(params)}"
        params.append(offset)
        tail += f" OFFSET ${len(params)}"
    return await pool.fetch(
        f"SELECT {_EVENT_COLS} FROM events WHERE {where} "
        f"ORDER BY starts_at DESC{tail}",
        *params,
    )


async def count_past_events(
    pool: asyncpg.Pool, *, search: str | None = None,
    kind: str | None = None, status: str | None = None,
) -> int:
    """Число прошедших событий под текущие фильтры (для пагинации, этап 36)."""
    where, params = _events_filters("starts_at < now()", search, kind, status)
    return await pool.fetchval(
        f"SELECT count(*) FROM events WHERE {where}", *params
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


async def ticket_counts_by_event(pool: asyncpg.Pool) -> dict[int, dict[str, int]]:
    """Число оплаченных билетов по типам для всех событий — без N+1.

    {event_id: {ticket_type: count}}. Занятые места считаются из этого в
    services.events.seats_occupied (пара = 2 места).
    """
    rows = await pool.fetch(
        "SELECT event_id, ticket_type, count(*) AS c FROM tickets "
        "WHERE status = 'paid' GROUP BY event_id, ticket_type"
    )
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["event_id"], {})[r["ticket_type"]] = r["c"]
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


async def get_price_tiers(pool: asyncpg.Pool, event_id: int) -> list[dict]:
    """Пороги динамической цены события (этап 45), отсортированные по дате/типу."""
    rows = await pool.fetch(
        "SELECT ticket_type, days_before, price FROM event_price_tiers "
        "WHERE event_id = $1 ORDER BY days_before, ticket_type",
        event_id,
    )
    return [dict(r) for r in rows]


async def set_price_tiers(
    pool: asyncpg.Pool, event_id: int, tiers: list[tuple[str, int, int]]
) -> None:
    """Перезаписывает пороги события: полностью удаляет старые и вставляет новые.

    tiers — список (ticket_type, days_before, price). Пустой список = порогов нет
    (билеты продаются по базовой цене типа).
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                "DELETE FROM event_price_tiers WHERE event_id = $1", event_id
            )
            for ttype, days_before, price in tiers:
                await con.execute(
                    "INSERT INTO event_price_tiers "
                    "(event_id, ticket_type, days_before, price) VALUES ($1,$2,$3,$4)",
                    event_id, ttype, days_before, price,
                )


async def delete_event(pool: asyncpg.Pool, event_id: int) -> None:
    # Цены удалятся каскадом (FK ON DELETE CASCADE).
    await pool.execute("DELETE FROM events WHERE id = $1", event_id)


async def cancel_event(pool: asyncpg.Pool, event_id: int) -> bool:
    """Отменяет событие: проставляет canceled_at + скрывает (is_active=false).

    Идемпотентно: отменяет только ещё не отменённое событие. Рассылку купившим и
    пометку билетов на возврат делает фоновый джоб бота (services.event_notifications)
    — веб-процесс отдельный от бота. Возвращает True, если отменено этим вызовом.
    """
    row = await pool.fetchrow(
        """
        UPDATE events SET canceled_at = now(), is_active = false
        WHERE id = $1 AND canceled_at IS NULL
        RETURNING id
        """,
        event_id,
    )
    return row is not None
