"""Запросы статистики для дашборда (этап 20).

Источник дохода — succeeded-платежи (`payments.status='succeeded'`), момент дохода —
`payments.updated_at` (туда пишется now() при активации, см. repo.activate_payment /
activate_ticket_payment). Направление платежа:
  · подписка — `payments.kind` in ('new','renewal');
  · билет    — `payments.kind='ticket'`, конкретное направление = `events.kind`
               ('banya'/'retreat').

Все запросы — read-only агрегаты; пишем как чистый слой данных (без бизнес-логики).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import asyncpg

# Направление дохода для платежа: подписка либо тип события билета.
_DIRECTION_SQL = """
    CASE
        WHEN p.kind = 'ticket' THEN COALESCE(e.kind, 'ticket')
        ELSE 'subscription'
    END
"""


async def revenue_by_direction(
    pool: asyncpg.Pool, start: datetime, end: datetime
) -> dict[str, Decimal]:
    """Доход за [start, end) по направлениям: {direction: сумма}.

    direction ∈ {'subscription', 'banya', 'retreat', 'ticket'(прочие события)}.
    Пустые направления в словарь не попадают.
    """
    rows = await pool.fetch(
        f"""
        SELECT {_DIRECTION_SQL} AS direction,
               COALESCE(SUM(p.amount), 0) AS total
        FROM payments p
        LEFT JOIN events e ON e.id = p.event_id
        WHERE p.status = 'succeeded'
          AND p.updated_at >= $1 AND p.updated_at < $2
        GROUP BY direction
        """,
        start, end,
    )
    return {r["direction"]: r["total"] for r in rows}


async def revenue_total(pool: asyncpg.Pool, start: datetime, end: datetime) -> Decimal:
    """Суммарный доход за [start, end)."""
    val = await pool.fetchval(
        """
        SELECT COALESCE(SUM(amount), 0) FROM payments
        WHERE status = 'succeeded' AND updated_at >= $1 AND updated_at < $2
        """,
        start, end,
    )
    return val or Decimal(0)


async def revenue_buckets(
    pool: asyncpg.Pool, start: datetime, end: datetime, granularity: str
) -> dict[datetime, Decimal]:
    """Доход по корзинам времени для графика: {начало_корзины(UTC): сумма}.

    granularity: 'day' | 'week' | 'month'. Корзина — date_trunc по этому шагу.
    Пустые корзины здесь отсутствуют; их заполняет нулями слой представления,
    чтобы ось была без разрывов.
    """
    unit = granularity if granularity in ("day", "week", "month") else "day"
    rows = await pool.fetch(
        f"""
        SELECT date_trunc('{unit}', updated_at) AS bucket,
               COALESCE(SUM(amount), 0) AS total
        FROM payments
        WHERE status = 'succeeded' AND updated_at >= $1 AND updated_at < $2
        GROUP BY bucket
        ORDER BY bucket
        """,
        start, end,
    )
    return {r["bucket"]: r["total"] for r in rows}


async def active_subscribers(pool: asyncpg.Pool) -> int:
    """Число активных подписчиков на текущий момент."""
    val = await pool.fetchval(
        "SELECT count(*) FROM subscriptions WHERE status = 'active' AND end_date > now()"
    )
    return int(val or 0)


async def payments_count(pool: asyncpg.Pool, start: datetime, end: datetime) -> int:
    """Число успешных платежей за период (для среднего чека)."""
    val = await pool.fetchval(
        """
        SELECT count(*) FROM payments
        WHERE status = 'succeeded' AND updated_at >= $1 AND updated_at < $2
        """,
        start, end,
    )
    return int(val or 0)


async def referral_stats(
    pool: asyncpg.Pool, start: datetime, end: datetime
) -> dict[str, object]:
    """Эффективность рефералки за период.

    · invited     — приглашений создано (referrals по created_at в периоде);
    · qualified   — из них состоявшихся (первая покупка бани новичком: статусы
                    'qualified'/'accrued' по qualified_at в периоде);
    · bonus_paid  — выплачено бонусов пригласившим (bonus_ledger reason='referral_bonus',
                    delta>0, created_at в периоде), в рублях (1 бонус = 1 ₽).
    """
    invited = await pool.fetchval(
        "SELECT count(*) FROM referrals WHERE created_at >= $1 AND created_at < $2",
        start, end,
    )
    qualified = await pool.fetchval(
        """
        SELECT count(*) FROM referrals
        WHERE status IN ('qualified', 'accrued')
          AND qualified_at >= $1 AND qualified_at < $2
        """,
        start, end,
    )
    bonus_paid = await pool.fetchval(
        """
        SELECT COALESCE(SUM(delta), 0) FROM bonus_ledger
        WHERE reason = 'referral_bonus' AND delta > 0
          AND created_at >= $1 AND created_at < $2
        """,
        start, end,
    )
    return {
        "invited": int(invited or 0),
        "qualified": int(qualified or 0),
        "bonus_paid": bonus_paid or Decimal(0),
    }


async def first_payment_at(pool: asyncpg.Pool) -> datetime | None:
    """Дата первого успешного платежа — для режима «всё время»."""
    return await pool.fetchval(
        "SELECT min(updated_at) FROM payments WHERE status = 'succeeded'"
    )
