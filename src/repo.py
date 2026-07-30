"""Слой доступа к данным. Все таблицы — в схеме club_bot (search_path задан в db.py)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
from asyncpg.exceptions import UniqueViolationError

from .utils import add_period


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


async def get_user(pool: asyncpg.Pool, tg_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM users WHERE tg_id = $1", tg_id)


async def search_users(
    pool: asyncpg.Pool, query: str, limit: int = 25
) -> list[asyncpg.Record]:
    """Поиск участников по @username / имени / tg_id (частично, регистронезависимо).

    Для раздела «Подписки»: админ ищет человека не только по числовому ID, но и по
    нику/имени. Возвращает tg_id, username, first_name отсортированными по нику/имени.
    """
    like = f"%{query}%"
    return await pool.fetch(
        """
        SELECT tg_id, username, first_name
        FROM users
        WHERE username ILIKE $1 OR first_name ILIKE $1 OR CAST(tg_id AS TEXT) LIKE $1
        ORDER BY username NULLS LAST, first_name NULLS LAST, tg_id
        LIMIT $2
        """,
        like, limit,
    )


async def get_all_user_ids(pool: asyncpg.Pool) -> list[int]:
    """Все tg_id для рассылки (кроме заблокированных)."""
    rows = await pool.fetch(
        "SELECT tg_id FROM users WHERE is_blocked = false ORDER BY tg_id"
    )
    return [r["tg_id"] for r in rows]


# Сегменты аудитории для рассылки.
AUDIENCE_ALL = "all"
AUDIENCE_ACTIVE = "active"
AUDIENCE_FORMER = "former"
AUDIENCE_NEVER = "never"


async def get_audience_ids(pool: asyncpg.Pool, audience: str) -> list[int]:
    """tg_id для рассылки по сегменту (всегда без заблокированных).

    active — есть активная подписка; former — подписка была, но активной нет;
    never — нет ни одной подписки; всё прочее — все пользователи.
    """
    if audience == AUDIENCE_ACTIVE:
        sql = """
            SELECT DISTINCT u.tg_id FROM users u
            JOIN subscriptions s ON s.tg_id = u.tg_id
            WHERE u.is_blocked = false
              AND s.status = 'active' AND s.end_date > now()
            ORDER BY u.tg_id
        """
    elif audience == AUDIENCE_FORMER:
        sql = """
            SELECT u.tg_id FROM users u
            WHERE u.is_blocked = false
              AND EXISTS (SELECT 1 FROM subscriptions s WHERE s.tg_id = u.tg_id)
              AND NOT EXISTS (
                  SELECT 1 FROM subscriptions s
                  WHERE s.tg_id = u.tg_id
                    AND s.status = 'active' AND s.end_date > now()
              )
            ORDER BY u.tg_id
        """
    elif audience == AUDIENCE_NEVER:
        sql = """
            SELECT u.tg_id FROM users u
            WHERE u.is_blocked = false
              AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tg_id = u.tg_id)
            ORDER BY u.tg_id
        """
    else:  # AUDIENCE_ALL
        sql = "SELECT tg_id FROM users WHERE is_blocked = false ORDER BY tg_id"
    rows = await pool.fetch(sql)
    return [r["tg_id"] for r in rows]


async def set_user_blocked(pool: asyncpg.Pool, tg_id: int, blocked: bool) -> None:
    await pool.execute(
        "UPDATE users SET is_blocked = $2, updated_at = now() WHERE tg_id = $1",
        tg_id,
        blocked,
    )


# ── Рантайм-настройки (bot_settings, этап 8) ─────────────────────────────────
async def get_settings(pool: asyncpg.Pool, keys: list[str]) -> dict[str, str]:
    """Значения настроек по списку ключей (отсутствующие ключи просто не попадут)."""
    rows = await pool.fetch(
        "SELECT key, value FROM bot_settings WHERE key = ANY($1::text[])", keys
    )
    return {r["key"]: r["value"] for r in rows}


async def set_setting(pool: asyncpg.Pool, key: str, value: str) -> None:
    await pool.execute(
        """
        INSERT INTO bot_settings(key, value)
        VALUES($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        key,
        value,
    )


async def get_fsm_stuck(pool: asyncpg.Pool, limit: int = 30) -> list[asyncpg.Record]:
    """Пользователи и их последний шаг (FSM-экран) — кто где находится/застрял.

    Берём из лога состояний только незавершённые шаги (state не пуст), свежие —
    сверху. Присоединяем username/имя для читаемости.
    """
    return await pool.fetch(
        """
        SELECT f.tg_id, f.state, f.updated_at, u.username, u.first_name
        FROM fsm_states f
        LEFT JOIN users u ON u.tg_id = f.tg_id
        WHERE f.state IS NOT NULL
        ORDER BY f.updated_at DESC
        LIMIT $1
        """,
        limit,
    )


async def add_event(pool: asyncpg.Pool, tg_id: int, event: str, keep: int = 50) -> None:
    """Пишет действие пользователя в журнал user_events (для просмотра пути).

    Самоограничение роста: после вставки удаляет всё, кроме последних `keep`
    записей этого пользователя. Не должна ронять обработку апдейта — вызывающий
    оборачивает в try/except.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO user_events(tg_id, event) VALUES($1, $2)", tg_id, event
            )
            await conn.execute(
                """
                DELETE FROM user_events
                WHERE tg_id = $1 AND id NOT IN (
                    SELECT id FROM user_events
                    WHERE tg_id = $1 ORDER BY id DESC LIMIT $2
                )
                """,
                tg_id,
                keep,
            )


async def get_user_events(
    pool: asyncpg.Pool, tg_id: int, limit: int = 20
) -> list[asyncpg.Record]:
    """Последние действия пользователя (свежие сверху) — для раздела «История»."""
    return await pool.fetch(
        "SELECT event, created_at FROM user_events "
        "WHERE tg_id = $1 ORDER BY id DESC LIMIT $2",
        tg_id,
        limit,
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


# ── Цены за период внутри ступени (tier_prices) ──────────────────────────────
async def get_all_tier_prices(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT tier_id, months, unit, price FROM tier_prices")


async def get_tier_prices(pool: asyncpg.Pool, tier_id: int) -> dict[tuple[int, str], "Decimal"]:
    """Переопределения цены {(значение, единица): цена} для одной ступени."""
    rows = await pool.fetch(
        "SELECT months, unit, price FROM tier_prices WHERE tier_id = $1", tier_id
    )
    return {(r["months"], r["unit"]): r["price"] for r in rows}


async def set_tier_price(
    pool: asyncpg.Pool, tier_id: int, value: int, unit: str,
    price: Decimal | int | float,
) -> None:
    await pool.execute(
        """
        INSERT INTO tier_prices(tier_id, months, unit, price)
        VALUES($1, $2, $3, $4)
        ON CONFLICT (tier_id, months, unit) DO UPDATE
            SET price = EXCLUDED.price, updated_at = now()
        """,
        tier_id,
        value,
        unit,
        Decimal(str(price)),
    )


async def delete_tier_price(
    pool: asyncpg.Pool, tier_id: int, value: int, unit: str
) -> None:
    """Сброс переопределения — период снова считается как ставка×значение."""
    await pool.execute(
        "DELETE FROM tier_prices WHERE tier_id = $1 AND months = $2 AND unit = $3",
        tier_id,
        value,
        unit,
    )


async def count_active_members(pool: asyncpg.Pool) -> int:
    """Сколько мест в клубе занято = число участников с активной подпиской.

    По этому числу движок определяет текущую ценовую ступень.
    """
    row = await pool.fetchrow(
        """
        SELECT COUNT(DISTINCT tg_id) AS n
        FROM subscriptions
        WHERE status = 'active' AND end_date > now()
        """
    )
    return row["n"] or 0


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


async def upsert_duration(
    pool: asyncpg.Pool, value: int, unit: str = "month", is_active: bool = True
) -> None:
    """Добавляет/включает длительность (значение + единица). months хранит значение.

    Новая длительность встаёт В КОНЕЦ списка (sort_order = max+10) — порядок потом
    меняется вручную в админке. При реактивации существующей порядок сохраняется.
    """
    await pool.execute(
        """
        INSERT INTO durations(months, unit, sort_order, is_active)
        VALUES($1, $2, COALESCE((SELECT MAX(sort_order) FROM durations), 0) + 10, $3)
        ON CONFLICT (months, unit) DO UPDATE SET is_active = EXCLUDED.is_active
        """,
        value,
        unit,
        is_active,
    )


async def move_duration(pool: asyncpg.Pool, duration_id: int, direction: str) -> bool:
    """Сдвигает длительность вверх/вниз в списке (direction='up'|'down').

    Нормализует sort_order всех строк по текущему порядку и применяет перестановку
    с соседом — устойчиво к дублям/пропускам в sort_order. Возвращает False, если
    двигать некуда (край списка) или длительность не найдена.
    """
    rows = await pool.fetch("SELECT id FROM durations ORDER BY sort_order, months, id")
    ids = [r["id"] for r in rows]
    if duration_id not in ids:
        return False
    i = ids.index(duration_id)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(ids):
        return False
    ids[i], ids[j] = ids[j], ids[i]
    async with pool.acquire() as con:
        async with con.transaction():
            for pos, did in enumerate(ids):
                await con.execute(
                    "UPDATE durations SET sort_order = $1 WHERE id = $2", pos * 10, did
                )
    return True


async def set_duration_active(pool: asyncpg.Pool, duration_id: int, is_active: bool) -> bool:
    row = await pool.fetchrow(
        "UPDATE durations SET is_active = $2 WHERE id = $1 RETURNING id",
        duration_id,
        is_active,
    )
    return row is not None


async def delete_duration(pool: asyncpg.Pool, duration_id: int) -> bool:
    """Удаляет длительность вместе с заданными для этого периода ценами.

    Подписки/платежи хранят снимок (months/unit) и FK на durations не имеют —
    удаление длительности не затрагивает уже оформленные подписки. Заданные для
    периода переопределения цены (tier_prices по всем ступеням) чистим, чтобы не
    оставлять «осиротевшие» строки. Возвращает True, если строка была удалена.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            d = await conn.fetchrow(
                "SELECT months, unit FROM durations WHERE id = $1", duration_id
            )
            if d is None:
                return False
            await conn.execute(
                "DELETE FROM tier_prices WHERE months = $1 AND unit = $2",
                d["months"],
                d["unit"],
            )
            await conn.execute("DELETE FROM durations WHERE id = $1", duration_id)
    return True


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
    unit: str = "month",
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO subscriptions(tg_id, tier_id, fixed_price, months, unit, end_date, source, status)
        VALUES($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        tg_id,
        tier_id,
        Decimal(str(fixed_price)),
        months,
        unit,
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


async def get_last_subscription(pool: asyncpg.Pool, tg_id: int) -> asyncpg.Record | None:
    """Последняя подписка пользователя независимо от статуса."""
    return await pool.fetchrow(
        "SELECT * FROM subscriptions WHERE tg_id = $1 ORDER BY id DESC LIMIT 1",
        tg_id,
    )


async def set_user_email(pool: asyncpg.Pool, tg_id: int, email: str) -> None:
    """Сохраняет реальный email покупателя (для чека 54-ФЗ). Задел под будущий сбор."""
    await pool.execute(
        "UPDATE users SET email = $2, updated_at = now() WHERE tg_id = $1",
        tg_id,
        email,
    )


# ── Мероприятия (events) — раздел «Мероприятия» в боте (этап 13) ──────────────
_EVENT_COLS = (
    "id, kind, title, starts_at, gender_balance, seats_total, seats_male, "
    "seats_female, show_in_advance, subscriber_discount_percent, address, "
    "rules_text, is_active"
)


async def list_events(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Все события (фильтрация по правилам показа — в services.events)."""
    return await pool.fetch(f"SELECT {_EVENT_COLS} FROM events ORDER BY starts_at")


async def get_event(pool: asyncpg.Pool, event_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        f"SELECT {_EVENT_COLS} FROM events WHERE id = $1", event_id
    )


async def get_event_prices(pool: asyncpg.Pool, event_id: int) -> dict[str, int]:
    """Цены по типам билетов события: {ticket_type: price}."""
    rows = await pool.fetch(
        "SELECT ticket_type, price FROM event_ticket_prices WHERE event_id = $1",
        event_id,
    )
    return {r["ticket_type"]: r["price"] for r in rows}


async def get_event_price_tiers(
    pool: asyncpg.Pool, event_id: int
) -> dict[str, list[tuple[int, int]]]:
    """Пороги динамической цены события (этап 45): {ticket_type: [(days_before, price)]}."""
    rows = await pool.fetch(
        "SELECT ticket_type, days_before, price FROM event_price_tiers "
        "WHERE event_id = $1 ORDER BY ticket_type, days_before",
        event_id,
    )
    out: dict[str, list[tuple[int, int]]] = {}
    for r in rows:
        out.setdefault(r["ticket_type"], []).append((r["days_before"], r["price"]))
    return out


async def prices_by_event(pool: asyncpg.Pool) -> dict[int, dict[str, int]]:
    """Цены всех событий сразу (для фильтра распроданных без N+1)."""
    rows = await pool.fetch("SELECT event_id, ticket_type, price FROM event_ticket_prices")
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["event_id"], {})[r["ticket_type"]] = r["price"]
    return out


async def ticket_counts_by_event(pool: asyncpg.Pool) -> dict[int, dict[str, int]]:
    """Оплаченные билеты всех событий: {event_id: {ticket_type: count}}."""
    rows = await pool.fetch(
        "SELECT event_id, ticket_type, count(*) AS c FROM tickets "
        "WHERE status = 'paid' GROUP BY event_id, ticket_type"
    )
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["event_id"], {})[r["ticket_type"]] = r["c"]
    return out


# ── Платежи (payments) ───────────────────────────────────────────────────────
async def create_payment(
    pool: asyncpg.Pool,
    *,
    yookassa_payment_id: str,
    idempotence_key: str,
    tg_id: int,
    tier_id: int | None,
    months: int,
    fixed_price: Decimal | int | float,
    amount: Decimal | int | float,
    confirmation_url: str | None,
    status: str = "pending",
    kind: str = "new",
    unit: str = "month",
    promo_id: int | None = None,
    event_id: int | None = None,
    ticket_type: str | None = None,
    service_product_id: int | None = None,
    quantity: int | None = None,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO payments(
            yookassa_payment_id, idempotence_key, tg_id, tier_id, months, unit,
            fixed_price, amount, confirmation_url, status, kind, promo_id,
            event_id, ticket_type, service_product_id, quantity
        )
        VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        RETURNING id
        """,
        yookassa_payment_id,
        idempotence_key,
        tg_id,
        tier_id,
        months,
        unit,
        Decimal(str(fixed_price)),
        Decimal(str(amount)),
        confirmation_url,
        status,
        kind,
        promo_id,
        event_id,
        ticket_type,
        service_product_id,
        quantity,
    )
    return row["id"]


# ── Продукты услуг «по количеству»: йога/консультации (этапы 46/47) ───────────
async def list_service_products(
    pool: asyncpg.Pool, category: str, *, active_only: bool = False
) -> list[asyncpg.Record]:
    """Продукты категории в порядке показа. active_only — только включённые."""
    if active_only:
        return await pool.fetch(
            "SELECT * FROM service_products WHERE category = $1 AND is_active "
            "ORDER BY sort_order, id",
            category,
        )
    return await pool.fetch(
        "SELECT * FROM service_products WHERE category = $1 ORDER BY sort_order, id",
        category,
    )


async def get_service_product(pool: asyncpg.Pool, product_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM service_products WHERE id = $1", product_id
    )


async def update_service_product(
    pool: asyncpg.Pool, product_id: int, *,
    price: int, subscriber_discount_percent: int, is_active: bool,
) -> None:
    """Правит цену/скидку/активность продукта (набор продуктов задаёт миграция-сид)."""
    await pool.execute(
        "UPDATE service_products SET price = $2, subscriber_discount_percent = $3, "
        "is_active = $4 WHERE id = $1",
        product_id, price, subscriber_discount_percent, is_active,
    )


async def activate_service_payment(pool: asyncpg.Pool, yk_id: str) -> bool:
    """Помечает платёж услуги succeeded ровно один раз. True — если это первая пометка.

    Услуга не выдаёт билет и не занимает место — активация лишь фиксирует оплату
    (атомарно, без дублей): начисления рефералки, уведомление админам и сообщение
    пользователю вешаются вызывающим кодом на факт `created=True`.
    """
    row = await pool.fetchrow(
        "UPDATE payments SET status = 'succeeded', updated_at = now() "
        "WHERE yookassa_payment_id = $1 AND status <> 'succeeded' RETURNING id",
        yk_id,
    )
    return row is not None


async def get_payment_by_yk_id(pool: asyncpg.Pool, yk_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM payments WHERE yookassa_payment_id = $1", yk_id
    )


async def get_pending_payments(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Незавершённые платежи — их опрашивает фоновый поллер."""
    return await pool.fetch(
        "SELECT * FROM payments WHERE status = 'pending' ORDER BY id"
    )


async def mark_payment_canceled(pool: asyncpg.Pool, yk_id: str) -> None:
    await pool.execute(
        "UPDATE payments SET status = 'canceled', updated_at = now() "
        "WHERE yookassa_payment_id = $1 AND status = 'pending'",
        yk_id,
    )


async def activate_payment(
    pool: asyncpg.Pool, yk_id: str
) -> tuple[int | None, bool]:
    """Атомарно активирует/продлевает подписку по успешному платежу. Идемпотентно.

    Берёт строку платежа под блокировку (FOR UPDATE). Если подписка уже создана
    (subscription_id заполнен) — ничего не делает: повторный вызов (поллер + кнопка
    «Проверить» одновременно, повторная оплата того же платежа) НЕ создаёт дубль.

    Иначе по kind платежа:
      'new'     — создаёт подписку (end_date = now + months);
      'renewal' — продлевает АКТИВНУЮ подписку юзера (end_date += months, та же
                  строка, зафиксированная цена сохраняется). Если активной нет
                  (истекла между оплатой и подтверждением) — fallback: создаёт
                  новую от now по оплаченной ставке (деньги уже приняты).

    Возвращает (subscription_id, created):
      created=True  — подписка создана/продлена этим вызовом (уведомить пользователя);
      created=False — платёж не найден (id=None) либо уже был активирован ранее.
    """
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            pay = await conn.fetchrow(
                "SELECT * FROM payments WHERE yookassa_payment_id = $1 FOR UPDATE",
                yk_id,
            )
            if pay is None:
                return None, False
            if pay["subscription_id"] is not None:
                return pay["subscription_id"], False  # уже активирован — без дубля

            months = pay["months"]
            unit = pay["unit"]

            if pay["kind"] == "renewal":
                active = await conn.fetchrow(
                    """
                    SELECT * FROM subscriptions
                    WHERE tg_id = $1 AND status = 'active' AND end_date > now()
                    ORDER BY end_date DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    pay["tg_id"],
                )
                if active is not None:
                    new_end = add_period(active["end_date"], months, unit)
                    await conn.execute(
                        "UPDATE subscriptions SET end_date = $2, updated_at = now() "
                        "WHERE id = $1",
                        active["id"],
                        new_end,
                    )
                    await conn.execute(
                        "UPDATE payments SET status = 'succeeded', subscription_id = $2, "
                        "updated_at = now() WHERE id = $1",
                        pay["id"],
                        active["id"],
                    )
                    return active["id"], True
                # активная подписка истекла до подтверждения — оформим новую от now

            source = "promo" if pay["promo_id"] is not None else "payment"
            # Фиксация промо-цены (этап 44): продление пойдёт по этой цене, а не по
            # общей цене продления, только если промокод фиксирует цену (fixes_price).
            # Процентный промокод даёт source='promo', но цену не фиксирует.
            price_locked = False
            if pay["promo_id"] is not None:
                pr = await conn.fetchrow(
                    "SELECT fixes_price FROM promo_codes WHERE id = $1", pay["promo_id"]
                )
                price_locked = bool(pr and pr["fixes_price"])
            sub = await conn.fetchrow(
                """
                INSERT INTO subscriptions(
                    tg_id, tier_id, fixed_price, months, unit, end_date, source, status,
                    price_locked
                )
                VALUES($1, $2, $3, $4, $5, $6, $7, 'active', $8)
                RETURNING id
                """,
                pay["tg_id"],
                pay["tier_id"],
                pay["fixed_price"],
                months,
                unit,
                add_period(now, months, unit),
                source,
                price_locked,
            )
            await conn.execute(
                "UPDATE payments SET status = 'succeeded', subscription_id = $2, "
                "updated_at = now() WHERE id = $1",
                pay["id"],
                sub["id"],
            )
            await _record_promo_redemption(conn, pay)
            return sub["id"], True


async def _record_promo_redemption(conn, pay: asyncpg.Record) -> None:
    """Внутри транзакции активации: фиксирует применение промокода и +1 к счётчику.

    Уникальность (promo_id, tg_id) защищает от двойного учёта; инкремент
    used_count делаем только когда запись действительно создана (этот платёж).
    """
    if pay["promo_id"] is None:
        return
    row = await conn.fetchrow(
        """
        INSERT INTO promo_redemptions(promo_id, tg_id, payment_id)
        VALUES($1, $2, $3)
        ON CONFLICT (promo_id, tg_id) DO NOTHING
        RETURNING id
        """,
        pay["promo_id"],
        pay["tg_id"],
        pay["id"],
    )
    if row is not None:
        await conn.execute(
            "UPDATE promo_codes SET used_count = used_count + 1, updated_at = now() "
            "WHERE id = $1",
            pay["promo_id"],
        )


# ── Билеты (tickets) — этап 14 ────────────────────────────────────────────────
async def get_event_ticket_counts(pool: asyncpg.Pool, event_id: int) -> dict[str, int]:
    """Число оплаченных билетов по типам для события: {ticket_type: count}."""
    rows = await pool.fetch(
        "SELECT ticket_type, count(*) AS c FROM tickets "
        "WHERE event_id = $1 AND status = 'paid' GROUP BY ticket_type",
        event_id,
    )
    return {r["ticket_type"]: r["c"] for r in rows}


async def get_ticket(pool: asyncpg.Pool, ticket_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)


async def list_active_tickets(pool: asyncpg.Pool, tg_id: int) -> list[asyncpg.Record]:
    """Активные билеты пользователя (этап 18): оплаченные на будущие события.

    Прошедшие события скрыты (`starts_at > now()`). Посещённые билеты (отмечен приход
    на входе, `attended_at IS NOT NULL`, этап 34) тоже скрыты — билет использован,
    возврат по нему недоступен. К каждому билету подтягиваем данные события
    (название/тип/дата/адрес) для карточки. Сортировка — по дате.
    """
    return await pool.fetch(
        """
        SELECT t.id, t.event_id, t.ticket_type, t.price, t.status, t.rules_agreed,
               t.refund_requested,
               e.title, e.kind, e.starts_at, e.address
        FROM tickets t
        JOIN events e ON e.id = t.event_id
        WHERE t.tg_id = $1 AND t.status = 'paid'
          AND t.attended_at IS NULL AND e.starts_at > now()
        ORDER BY e.starts_at
        """,
        tg_id,
    )


async def request_ticket_refund(pool: asyncpg.Pool, ticket_id: int, tg_id: int) -> bool:
    """Ставит билету пометку «возврат запрошен» (этап 18). Идемпотентно.

    Статус билета НЕ меняем — возврат ручной, место не освобождаем до факта
    возврата. Обновляем только свой оплаченный билет, у которого запрос ещё не стоял.
    Возвращает True, если флаг проставлен этим вызовом (False — уже стоял/не подошёл).
    """
    row = await pool.fetchrow(
        """
        UPDATE tickets SET refund_requested = true, refund_requested_at = now()
        WHERE id = $1 AND tg_id = $2 AND status = 'paid' AND refund_requested = false
        RETURNING id
        """,
        ticket_id,
        tg_id,
    )
    return row is not None


async def set_ticket_rules_agreed(pool: asyncpg.Pool, ticket_id: int) -> None:
    await pool.execute(
        "UPDATE tickets SET rules_agreed = true WHERE id = $1", ticket_id
    )


# ── Отметка фактического возврата билета (этап 21) ────────────────────────────
def _ticket_search_clause(params: list, search: str | None) -> str | None:
    """SQL-фрагмент поиска билета: имя / @username / Telegram ID + НОМЕР билета (этап 33).

    Аппендит значения в `params` (сквозная нумерация $-параметров) и возвращает условие
    в скобках, либо None для пустого поиска. Правила:
    - `#123` (или `# 123`) — точный номер билета `t.id = 123`;
    - просто число `123` — частичный поиск по tg_id ИЛИ точный номер билета (`t.id`);
    - текст — частичный регистронезависимый по @username/имени.
    """
    s = (search or "").strip()
    if not s:
        return None
    if s.startswith("#") and s[1:].strip().isdigit():
        params.append(int(s[1:].strip()))
        return f"t.id = ${len(params)}"
    params.append(f"%{s}%")
    i = len(params)
    sub = (f"u.username ILIKE ${i} OR u.first_name ILIKE ${i} "
           f"OR CAST(t.tg_id AS TEXT) LIKE ${i}")
    if s.isdigit():
        params.append(int(s))
        sub += f" OR t.id = ${len(params)}"
    return f"({sub})"


def _sold_tickets_filters(
    event_id: int | None, search: str | None, status: str | None,
    date_from=None, date_to=None,
) -> tuple[str, list]:
    """Строит WHERE-условие и параметры для списка/счётчика проданных билетов (этап 32).

    Поиск — по имени / @username / Telegram ID / номеру билета (`#N` или число; этап 33).
    status: 'paid' (оплачен, без запроса возврата) · 'refund_requested' · 'refunded' ·
    иначе все ('paid'+'refunded'). date_from/date_to — диапазон ДАТЫ ПОКУПКИ (включительно).
    """
    clauses = ["t.status IN ('paid', 'refunded')"]
    params: list = []
    if event_id is not None:
        params.append(event_id)
        clauses.append(f"t.event_id = ${len(params)}")
    if status == "paid":
        clauses.append("t.status = 'paid' AND t.refund_requested = false")
    elif status == "refund_requested":
        clauses.append("t.status = 'paid' AND t.refund_requested = true")
    elif status == "refunded":
        clauses.append("t.status = 'refunded'")
    elif status == "attended":
        clauses.append("t.status = 'paid' AND t.attended_at IS NOT NULL")
    elif status == "not_attended":
        clauses.append("t.status = 'paid' AND t.attended_at IS NULL")
    if date_from is not None:
        params.append(date_from)
        clauses.append(f"t.created_at::date >= ${len(params)}")
    if date_to is not None:
        params.append(date_to)
        clauses.append(f"t.created_at::date <= ${len(params)}")
    search_clause = _ticket_search_clause(params, search)
    if search_clause:
        clauses.append(search_clause)
    return " AND ".join(clauses), params


async def list_sold_tickets(
    pool: asyncpg.Pool, event_id: int | None = None, *,
    search: str | None = None, status: str | None = None,
    date_from=None, date_to=None,
    limit: int | None = None, offset: int = 0,
) -> list[asyncpg.Record]:
    """Проданные билеты для веб-админки: оплаченные и уже возвращённые (этап 32).

    Фильтры: событие · поиск по покупателю · статус · диапазон даты покупки.
    Пагинация: limit/offset. Сортировка: сначала запрошенные на возврат, затем свежие.
    """
    where, params = _sold_tickets_filters(event_id, search, status, date_from, date_to)
    tail = ""
    if limit is not None:
        params.append(limit)
        tail += f" LIMIT ${len(params)}"
        params.append(offset)
        tail += f" OFFSET ${len(params)}"
    return await pool.fetch(
        f"""
        SELECT t.id, t.tg_id, t.ticket_type, t.price, t.status,
               t.refund_requested, t.refund_requested_at,
               t.refunded_at, t.refunded_by,
               t.refund_notified_at, t.refund_notify_failed, t.created_at,
               t.attended_at, t.attended_by,
               u.username, u.first_name,
               e.id AS event_id, e.title, e.kind, e.starts_at
        FROM tickets t
        JOIN events e ON e.id = t.event_id
        LEFT JOIN users u ON u.tg_id = t.tg_id
        WHERE {where}
        ORDER BY (t.status = 'paid' AND t.refund_requested) DESC,
                 t.created_at DESC{tail}
        """,
        *params,
    )


async def count_sold_tickets(
    pool: asyncpg.Pool, event_id: int | None = None, *,
    search: str | None = None, status: str | None = None,
    date_from=None, date_to=None,
) -> int:
    """Число проданных билетов под текущие фильтры (для пагинации, этап 32)."""
    where, params = _sold_tickets_filters(event_id, search, status, date_from, date_to)
    return await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM tickets t
        LEFT JOIN users u ON u.tg_id = t.tg_id
        WHERE {where}
        """,
        *params,
    )


async def list_checkin_tickets(
    pool: asyncpg.Pool, event_id: int | None = None, search: str | None = None,
    date_from=None, date_to=None,
) -> list[asyncpg.Record]:
    """Оплаченные билеты для печатного списка на вход (CSV, этап 32).

    Только 'paid' (возвращённые не приходят), по событию + опц. поиску + диапазону даты
    покупки. К билету — событие (название, дата) и Telegram ID. Сортировка по имени —
    удобно сверять людей на входе.
    """
    clauses = ["t.status = 'paid'"]
    params: list = []
    if event_id is not None:
        params.append(event_id)
        clauses.append(f"t.event_id = ${len(params)}")
    if date_from is not None:
        params.append(date_from)
        clauses.append(f"t.created_at::date >= ${len(params)}")
    if date_to is not None:
        params.append(date_to)
        clauses.append(f"t.created_at::date <= ${len(params)}")
    search_clause = _ticket_search_clause(params, search)
    if search_clause:
        clauses.append(search_clause)
    where = " AND ".join(clauses)
    return await pool.fetch(
        f"""
        SELECT t.tg_id, t.ticket_type, u.username, u.first_name,
               e.title, e.kind, e.starts_at
        FROM tickets t
        JOIN events e ON e.id = t.event_id
        LEFT JOIN users u ON u.tg_id = t.tg_id
        WHERE {where}
        ORDER BY lower(coalesce(u.first_name, '')), lower(coalesce(u.username, ''))
        """,
        *params,
    )


async def mark_ticket_refunded(
    pool: asyncpg.Pool, ticket_id: int, by: str
) -> dict | None:
    """Отмечает фактический возврат билета (менеджер вернул деньги вручную).

    Атомарно: статус 'paid'→'refunded' + аудит (refunded_at, refunded_by). Перевод
    освобождает место (занятость считается по 'paid') и убирает билет из «Моих
    билетов». Анти-возврат рефералки (этап 17): если приглашённый вернул билет на
    баню, по которой связь ещё лишь 'qualified' (бонус не начислен) — аннулируем её,
    чтобы джоб не начислил бонус пригласившему.

    Возвращает None, если билет не найден или уже возвращён; иначе dict с tg_id,
    event_id и флагом referral_voided.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE tickets
                SET status = 'refunded', refunded_at = now(), refunded_by = $2
                WHERE id = $1 AND status = 'paid'
                RETURNING tg_id, event_id
                """,
                ticket_id, by,
            )
            if row is None:
                return None
            voided = False
            ref = await conn.fetchrow(
                "SELECT id, status FROM referrals "
                "WHERE invitee_tg_id = $1 AND event_id = $2",
                row["tg_id"], row["event_id"],
            )
            if ref is not None and ref["status"] == "qualified":
                await conn.execute(
                    "UPDATE referrals SET status = 'void' "
                    "WHERE id = $1 AND status = 'qualified'",
                    ref["id"],
                )
                voided = True
            return {
                "tg_id": row["tg_id"],
                "event_id": row["event_id"],
                "referral_voided": voided,
            }


# Типы парных билетов (2 человека на входе) — для подсчёта людей в чек-ине (этап 34).
_PAIR_TICKET_TYPES = ("pair_mf", "pair_ff", "pair_mm")
# SQL-выражение «сколько людей по билету» (парный = 2, иначе 1).
_PEOPLE_EXPR = (
    "CASE WHEN ticket_type IN ('pair_mf', 'pair_ff', 'pair_mm') THEN 2 ELSE 1 END"
)


async def mark_ticket_attended(pool: asyncpg.Pool, ticket_id: int, by: str) -> str:
    """Отмечает приход по билету на входе (чек-ин, этап 34).

    Идемпотентно (защита от двойного прохода): обновляет только оплаченный и ещё не
    отмеченный билет, фиксируя время (attended_at) и логин админа (attended_by).
    Возвращает: 'ok' (отметил), 'already' (билет уже отмечен — повтор не задваивает),
    'not_found' (нет такого оплаченного билета).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE tickets SET attended_at = now(), attended_by = $2 "
            "WHERE id = $1 AND status = 'paid' AND attended_at IS NULL "
            "RETURNING id",
            ticket_id, by,
        )
        if row is not None:
            return "ok"
        t = await conn.fetchrow(
            "SELECT status, attended_at FROM tickets WHERE id = $1", ticket_id
        )
        if t is not None and t["status"] == "paid" and t["attended_at"] is not None:
            return "already"
        return "not_found"


async def unmark_ticket_attended(pool: asyncpg.Pool, ticket_id: int) -> bool:
    """Снимает отметку прихода (ошибочное нажатие на входе, этап 34).

    Возвращает True, если отметка была снята; False — если билета нет, он не оплачен
    или ещё не был отмечен.
    """
    row = await pool.fetchrow(
        "UPDATE tickets SET attended_at = NULL, attended_by = NULL "
        "WHERE id = $1 AND status = 'paid' AND attended_at IS NOT NULL "
        "RETURNING id",
        ticket_id,
    )
    return row is not None


async def checkin_stats(pool: asyncpg.Pool, event_id: int | None = None) -> dict:
    """Сводка чек-ина (этап 34): билетов и ЛЮДЕЙ — оплачено всего / пришло.

    Людей считаем с учётом парных билетов (парный = 2 человека). event_id=None — по
    всем событиям. Только оплаченные билеты (возвращённые в счёт входа не идут).
    """
    where = "status = 'paid'"
    params: list = []
    if event_id is not None:
        params.append(event_id)
        where += f" AND event_id = ${len(params)}"
    row = await pool.fetchrow(
        f"""
        SELECT
          count(*) AS tickets_total,
          count(*) FILTER (WHERE attended_at IS NOT NULL) AS tickets_in,
          COALESCE(SUM({_PEOPLE_EXPR}), 0) AS people_total,
          COALESCE(SUM({_PEOPLE_EXPR}) FILTER (WHERE attended_at IS NOT NULL), 0)
            AS people_in
        FROM tickets
        WHERE {where}
        """,
        *params,
    )
    return dict(row)


async def event_sales_summary(pool: asyncpg.Pool, event_id: int) -> dict:
    """Сводка продаж по событию для уведомления админам (этап 42), один запрос.

    · `tickets` — продано билетов (оплаченные; возвращённые не в счёт);
    · `people`  — занято мест (парный билет = 2 человека);
    · `amount`  — на какую сумму продано (фактически оплаченные цены билетов);
    · `seats`   — мест всего: при раздельном учёте М/Ж — их сумма, иначе
      `seats_total`; None = не ограничено.
    """
    row = await pool.fetchrow(
        f"""
        SELECT
            (SELECT count(*) FROM tickets t
              WHERE t.event_id = e.id AND t.status = 'paid') AS tickets,
            (SELECT COALESCE(SUM({_PEOPLE_EXPR}), 0) FROM tickets t
              WHERE t.event_id = e.id AND t.status = 'paid') AS people,
            (SELECT COALESCE(SUM(t.price), 0) FROM tickets t
              WHERE t.event_id = e.id AND t.status = 'paid') AS amount,
            CASE WHEN e.gender_balance
                 THEN COALESCE(e.seats_male, 0) + COALESCE(e.seats_female, 0)
                 ELSE e.seats_total
            END AS seats
        FROM events e
        WHERE e.id = $1
        """,
        event_id,
    )
    if row is None:
        return {"tickets": 0, "people": 0, "amount": Decimal(0), "seats": None}
    return {
        "tickets": int(row["tickets"]),
        "people": int(row["people"]),
        "amount": Decimal(row["amount"]),
        "seats": None if row["seats"] is None else int(row["seats"]),
    }


async def club_members_summary(pool: asyncpg.Pool) -> dict:
    """Сводка по клубу для уведомления админам (этап 42), один запрос.

    · `members` — активных подписчиков (люди, а не подписки: DISTINCT tg_id);
    · `amount`  — сумма их **последних успешных оплат**: сколько каждый заплатил
      за последнее продление. Выданные вручную/бесплатные участники (успешных
      платежей нет) считаются нулём — как в примере заказчика.
    """
    row = await pool.fetchrow(
        """
        WITH active AS (
            SELECT DISTINCT tg_id FROM subscriptions
            WHERE status = 'active' AND end_date > now()
        ), last_paid AS (
            SELECT a.tg_id, (
                SELECT p.amount FROM payments p
                WHERE p.tg_id = a.tg_id AND p.status = 'succeeded'
                  AND p.kind <> 'ticket'
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT 1
            ) AS amount
            FROM active a
        )
        SELECT count(*) AS members, COALESCE(SUM(amount), 0) AS amount FROM last_paid
        """
    )
    return {"members": int(row["members"]), "amount": Decimal(row["amount"])}


async def refunds_pending_notify(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Возвращённые билеты, по которым ещё не отправлено уведомление о возврате.

    Исключаем уже уведомлённые (refund_notified_at) и окончательно недоставленные
    (refund_notify_failed) — последние ждут ручной связи менеджера.
    """
    return await pool.fetch(
        """
        SELECT t.id, t.tg_id, t.event_id, e.title, e.kind, e.starts_at
        FROM tickets t
        JOIN events e ON e.id = t.event_id
        WHERE t.status = 'refunded'
          AND t.refunded_at IS NOT NULL
          AND t.refund_notified_at IS NULL
          AND t.refund_notify_failed = false
        ORDER BY t.refunded_at
        """
    )


async def mark_refund_notified(pool: asyncpg.Pool, ticket_id: int) -> None:
    """Фиксирует успешную доставку уведомления о возврате."""
    await pool.execute(
        "UPDATE tickets SET refund_notified_at = now() WHERE id = $1", ticket_id
    )


async def mark_refund_notify_failed(pool: asyncpg.Pool, ticket_id: int) -> None:
    """Помечает недоставку уведомления (пользователь заблокировал бота) — менеджер
    свяжется вручную. Исключает билет из повторных попыток рассылки."""
    await pool.execute(
        "UPDATE tickets SET refund_notify_failed = true WHERE id = $1", ticket_id
    )


# ── Мост «менеджер ↔ покупатель» (manager_messages, этап 21.1) ────────────────
async def queue_manager_message(
    pool: asyncpg.Pool, tg_id: int, ticket_id: int | None, admin_login: str, text: str
) -> int:
    """Ставит сообщение менеджера покупателю в очередь доставки (бот доставит)."""
    return await pool.fetchval(
        """
        INSERT INTO manager_messages(tg_id, ticket_id, direction, admin_login, text, status)
        VALUES($1, $2, 'out', $3, $4, 'pending')
        RETURNING id
        """,
        tg_id, ticket_id, admin_login, text,
    )


async def manager_messages_pending(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Исходящие сообщения менеджеров, ожидающие доставки ботом."""
    return await pool.fetch(
        "SELECT id, tg_id, text FROM manager_messages "
        "WHERE direction = 'out' AND status = 'pending' ORDER BY created_at"
    )


async def mark_manager_message_sent(pool: asyncpg.Pool, msg_id: int) -> None:
    await pool.execute(
        "UPDATE manager_messages SET status = 'sent', delivered_at = now() WHERE id = $1",
        msg_id,
    )


async def mark_manager_message_failed(pool: asyncpg.Pool, msg_id: int) -> None:
    await pool.execute(
        "UPDATE manager_messages SET status = 'failed' WHERE id = $1", msg_id
    )


async def has_manager_conversation(pool: asyncpg.Pool, tg_id: int) -> bool:
    """Писал ли кто-то из менеджеров этому покупателю за последние 14 дней.

    Ограничивает пересылку входящих: бот форвардит свободный текст админам только от
    тех, с кем переписка реально открыта (менеджер недавно писал), а не от всех юзеров.
    """
    val = await pool.fetchval(
        """
        SELECT 1 FROM manager_messages
        WHERE tg_id = $1 AND direction = 'out'
          AND created_at > now() - interval '14 days'
        LIMIT 1
        """,
        tg_id,
    )
    return val is not None


async def log_inbound_manager_message(
    pool: asyncpg.Pool, tg_id: int, text: str
) -> None:
    """Сохраняет ответ покупателя в историю переписки (direction='in')."""
    await pool.execute(
        "INSERT INTO manager_messages(tg_id, direction, text, status) "
        "VALUES($1, 'in', $2, 'received')",
        tg_id, text,
    )


async def manager_thread(pool: asyncpg.Pool, tg_id: int) -> list[asyncpg.Record]:
    """История переписки с покупателем (для карточки билета), свежие снизу."""
    return await pool.fetch(
        "SELECT direction, admin_login, text, status, created_at "
        "FROM manager_messages WHERE tg_id = $1 ORDER BY created_at",
        tg_id,
    )


async def user_ticket_titles(pool: asyncpg.Pool, tg_id: int) -> list[str]:
    """Названия событий, на которые у пользователя есть билеты — контекст для админов."""
    rows = await pool.fetch(
        "SELECT DISTINCT e.title FROM tickets t JOIN events e ON e.id = t.event_id "
        "WHERE t.tg_id = $1 ORDER BY e.title",
        tg_id,
    )
    return [r["title"] for r in rows]


async def unread_inbound_by_user(pool: asyncpg.Pool) -> dict[int, int]:
    """Число непрочитанных ответов покупателей по каждому tg_id — для пометок в списке."""
    rows = await pool.fetch(
        "SELECT tg_id, count(*) AS c FROM manager_messages "
        "WHERE direction = 'in' AND is_read = false GROUP BY tg_id"
    )
    return {r["tg_id"]: r["c"] for r in rows}


async def total_unread_inbound(pool: asyncpg.Pool) -> int:
    """Всего непрочитанных ответов покупателей (для счётчика в разделе)."""
    val = await pool.fetchval(
        "SELECT count(*) FROM manager_messages WHERE direction = 'in' AND is_read = false"
    )
    return int(val or 0)


async def mark_inbound_read(pool: asyncpg.Pool, tg_id: int) -> None:
    """Помечает входящие сообщения покупателя прочитанными (при открытии переписки)."""
    await pool.execute(
        "UPDATE manager_messages SET is_read = true "
        "WHERE tg_id = $1 AND direction = 'in' AND is_read = false",
        tg_id,
    )


# ── Уведомления по событиям (event_notifications, этап 20) ────────────────────
async def events_due_day_reminder(
    pool: asyncpg.Pool, before_ts: datetime
) -> list[asyncpg.Record]:
    """События, по которым пора слать напоминание «за 1 день».

    Условия: активно, не отменено, ещё не прошло (starts_at > now), наступает не
    позже `before_ts` (now + порог), и напоминание 'day_before' ещё не отправлено.
    """
    return await pool.fetch(
        """
        SELECT e.id, e.kind, e.title, e.starts_at, e.address
        FROM events e
        WHERE e.is_active = true AND e.canceled_at IS NULL
          AND e.starts_at > now() AND e.starts_at <= $1
          AND NOT EXISTS (
              SELECT 1 FROM event_notifications n
              WHERE n.event_id = e.id AND n.kind = 'day_before'
          )
        ORDER BY e.starts_at
        """,
        before_ts,
    )


async def events_pending_cancellation(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Отменённые события, по которым ещё не разослано уведомление об отмене."""
    return await pool.fetch(
        """
        SELECT e.id, e.kind, e.title, e.starts_at
        FROM events e
        WHERE e.canceled_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM event_notifications n
              WHERE n.event_id = e.id AND n.kind = 'canceled'
          )
        ORDER BY e.canceled_at
        """
    )


async def claim_event_notification(
    pool: asyncpg.Pool, event_id: int, kind: str
) -> bool:
    """Атомарно «занимает» рассылку (событие, тип). True — занято нами.

    INSERT ... ON CONFLICT DO NOTHING — защита от повторной рассылки при повторных
    прогонах планировщика и гонке параллельных проходов (аналог claim_reminder).
    """
    row = await pool.fetchrow(
        """
        INSERT INTO event_notifications(event_id, kind)
        VALUES($1, $2)
        ON CONFLICT (event_id, kind) DO NOTHING
        RETURNING event_id
        """,
        event_id,
        kind,
    )
    return row is not None


async def paid_ticket_holders(
    pool: asyncpg.Pool, event_id: int
) -> list[asyncpg.Record]:
    """Купившие билеты на событие (статус 'paid'): по одному на пользователя.

    Один пользователь мог купить несколько билетов — для рассылки нужен один адрес.
    """
    return await pool.fetch(
        """
        SELECT DISTINCT t.tg_id, u.username, u.first_name
        FROM tickets t
        JOIN users u ON u.tg_id = t.tg_id
        WHERE t.event_id = $1 AND t.status = 'paid'
        """,
        event_id,
    )


async def mark_event_tickets_refund(pool: asyncpg.Pool, event_id: int) -> int:
    """Помечает все оплаченные билеты события на ручной возврат (как этап 18).

    Ставит refund_requested на ещё не помеченных оплаченных билетах — они попадут
    в раздел возвратов веб-админки (этап 21). Возвращает число помеченных билетов.
    """
    val = await pool.fetchval(
        """
        WITH upd AS (
            UPDATE tickets SET refund_requested = true, refund_requested_at = now()
            WHERE event_id = $1 AND status = 'paid' AND refund_requested = false
            RETURNING id
        )
        SELECT count(*) FROM upd
        """,
        event_id,
    )
    return int(val or 0)


async def activate_ticket_payment(
    pool: asyncpg.Pool, yk_id: str
) -> tuple[int | None, bool, str]:
    """Атомарно выдаёт билет по успешному платежу. Идемпотентно, без овербукинга.

    Под блокировкой строки платежа (FOR UPDATE) и строки события (FOR UPDATE —
    сериализует параллельные выдачи на одно событие) пересчитывает занятые места
    по проданным билетам и проверяет, хватает ли мест под тип билета.

    Возвращает (ticket_id, created, reason):
      reason='created'   — билет выдан этим вызовом (уведомить пользователя);
      reason='already'   — платёж уже выдавал билет (повтор/гонка) — без дубля;
      reason='no_seats'  — мест не хватило (платёж помечен 'refund_due' — ручной возврат);
      reason='no_event'  — событие удалено (платёж помечен 'refund_due');
      reason='not_found' — платёж не найден.
    """
    from .services import events as ev

    async with pool.acquire() as conn:
        async with conn.transaction():
            pay = await conn.fetchrow(
                "SELECT * FROM payments WHERE yookassa_payment_id = $1 FOR UPDATE",
                yk_id,
            )
            if pay is None:
                return None, False, "not_found"
            if pay["ticket_id"] is not None:
                return pay["ticket_id"], False, "already"  # уже выдан — без дубля

            event = await conn.fetchrow(
                "SELECT * FROM events WHERE id = $1 FOR UPDATE", pay["event_id"]
            )
            if event is None:
                await conn.execute(
                    "UPDATE payments SET status = 'refund_due', updated_at = now() "
                    "WHERE id = $1",
                    pay["id"],
                )
                return None, False, "no_event"

            rows = await conn.fetch(
                "SELECT ticket_type, count(*) AS c FROM tickets "
                "WHERE event_id = $1 AND status = 'paid' GROUP BY ticket_type",
                pay["event_id"],
            )
            counts = {r["ticket_type"]: r["c"] for r in rows}
            occupied = ev.seats_occupied(counts)
            if not ev.has_seats(event, pay["ticket_type"], occupied):
                await conn.execute(
                    "UPDATE payments SET status = 'refund_due', updated_at = now() "
                    "WHERE id = $1",
                    pay["id"],
                )
                return None, False, "no_seats"

            ticket = await conn.fetchrow(
                """
                INSERT INTO tickets(tg_id, event_id, ticket_type, price, status, payment_id)
                VALUES($1, $2, $3, $4, 'paid', $5)
                RETURNING id
                """,
                pay["tg_id"],
                pay["event_id"],
                pay["ticket_type"],
                pay["amount"],
                pay["id"],
            )
            await conn.execute(
                "UPDATE payments SET status = 'succeeded', ticket_id = $2, "
                "updated_at = now() WHERE id = $1",
                pay["id"],
                ticket["id"],
            )
            # Промокод на билете (этап 16): расходуем активацию в той же транзакции.
            await _record_promo_redemption(conn, pay)
            return ticket["id"], True, "created"


# ── Промокоды (promo_codes / promo_redemptions, этап 7) ───────────────────────
async def create_promo(
    pool: asyncpg.Pool,
    *,
    code: str,
    kind: str,
    value: Decimal | int | float,
    max_activations: int | None,
    expires_at: datetime | None,
    fixes_price: bool,
) -> int | None:
    """Создаёт промокод. None — если код уже существует (нарушение уникальности)."""
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO promo_codes(
                code, kind, value, max_activations, expires_at, fixes_price
            )
            VALUES($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            code,
            kind,
            Decimal(str(value)),
            max_activations,
            expires_at,
            fixes_price,
        )
    except asyncpg.UniqueViolationError:
        return None
    return row["id"]


async def get_promo_by_code(pool: asyncpg.Pool, code: str) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM promo_codes WHERE code = $1", code)


async def get_promo(pool: asyncpg.Pool, promo_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM promo_codes WHERE id = $1", promo_id)


async def get_all_promos(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM promo_codes ORDER BY id DESC")


async def set_promo_active(pool: asyncpg.Pool, promo_id: int, is_active: bool) -> bool:
    row = await pool.fetchrow(
        "UPDATE promo_codes SET is_active = $2, updated_at = now() "
        "WHERE id = $1 RETURNING id",
        promo_id,
        is_active,
    )
    return row is not None


async def delete_promo(pool: asyncpg.Pool, promo_id: int) -> bool:
    """Удаляет промокод. Связанные записи об активациях (promo_redemptions)
    удаляются каскадом (ON DELETE CASCADE); ссылка в payments.promo_id обнуляется
    (ON DELETE SET NULL) — история платежей сохраняется. Уже оформленные по коду
    подписки не затрагиваются (цена уже зафиксирована). True — если строка удалена.
    """
    row = await pool.fetchrow(
        "DELETE FROM promo_codes WHERE id = $1 RETURNING id", promo_id
    )
    return row is not None


async def user_redeemed_promo(pool: asyncpg.Pool, promo_id: int, tg_id: int) -> bool:
    """Применял ли уже этот пользователь данный промокод (успешно)."""
    row = await pool.fetchrow(
        "SELECT 1 FROM promo_redemptions WHERE promo_id = $1 AND tg_id = $2",
        promo_id,
        tg_id,
    )
    return row is not None


async def expire_due_subscriptions(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Помечает истёкшие активные подписки 'expired'. Возвращает строки (id, tg_id).

    Вызывается фоновой проверкой окончаний: по возвращённым юзерам бот кикает из
    группы и шлёт уведомление. Перевод в 'expired' освобождает место (счётчик
    активных падает) и сбрасывает зафиксированную цену — новая подписка оформится
    по актуальной ступени.
    """
    return await pool.fetch(
        """
        UPDATE subscriptions
        SET status = 'expired', updated_at = now()
        WHERE status = 'active' AND end_date <= now()
        RETURNING id, tg_id
        """
    )


# ── Напоминания о продлении (subscription_reminders, этап 6) ──────────────────
async def get_subscriptions_for_reminders(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Активные ещё не истёкшие подписки + уже отправленные по ним типы напоминаний.

    Возвращает строки с полями подписки/пользователя и массивом `sent` (типы
    напоминаний, уже отправленные по этой подписке) — джоб по нему решает, что
    ещё нужно отправить.
    """
    return await pool.fetch(
        """
        SELECT s.id, s.tg_id, s.end_date, s.fixed_price, s.unit, s.price_locked,
               u.username, u.first_name,
               COALESCE(
                   array_agg(r.kind) FILTER (WHERE r.kind IS NOT NULL),
                   ARRAY[]::text[]
               ) AS sent
        FROM subscriptions s
        JOIN users u ON u.tg_id = s.tg_id
        LEFT JOIN subscription_reminders r ON r.subscription_id = s.id
        WHERE s.status = 'active' AND s.end_date > now()
        GROUP BY s.id, u.username, u.first_name
        """
    )


async def claim_reminder(pool: asyncpg.Pool, subscription_id: int, kind: str) -> bool:
    """Атомарно «занимает» отправку напоминания (подписка, тип). True — занято нами.

    INSERT ... ON CONFLICT DO NOTHING: если строка уже была (напоминание этого типа
    отправлялось), вернётся False и сообщение повторно не уйдёт — защита от дублей
    при повторных прогонах планировщика и гонке параллельных проходов.
    """
    row = await pool.fetchrow(
        """
        INSERT INTO subscription_reminders(subscription_id, kind)
        VALUES($1, $2)
        ON CONFLICT (subscription_id, kind) DO NOTHING
        RETURNING subscription_id
        """,
        subscription_id,
        kind,
    )
    return row is not None


async def cancel_active_subscriptions(pool: asyncpg.Pool, tg_id: int) -> int:
    """Аннулирует все активные подписки участника (status → cancelled).

    Освобождает место (счётчик активных падает). Возвращает число аннулированных.
    Фактический кик из группы добавится на этапах 4–5.
    """
    rows = await pool.fetch(
        """
        UPDATE subscriptions
        SET status = 'cancelled', updated_at = now()
        WHERE tg_id = $1 AND status = 'active'
        RETURNING id
        """,
        tg_id,
    )
    return len(rows)


# ── Подписки для веб-админки (этап 19) ────────────────────────────────────────
async def list_active_subscriptions(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Активные (не истёкшие) подписки + данные пользователя — для раздела «Подписки».

    Сортировка по ближайшему окончанию (кому продлевать срочнее — выше).
    """
    return await pool.fetch(
        """
        SELECT s.id, s.tg_id, s.fixed_price, s.unit, s.end_date, s.source,
               u.username, u.first_name
        FROM subscriptions s
        JOIN users u ON u.tg_id = s.tg_id
        WHERE s.status = 'active' AND s.end_date > now()
        ORDER BY s.end_date ASC
        """
    )


async def get_subscription(pool: asyncpg.Pool, sub_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM subscriptions WHERE id = $1", sub_id)


async def set_subscription_end_date(
    pool: asyncpg.Pool, sub_id: int, end_date: datetime
) -> bool:
    """Меняет дату окончания активной подписки (ручное продление из веб-админки).

    Обновляем только активную подписку. True — обновлено. Цену (`fixed_price`) не
    трогаем — продление без перерыва сохраняет зафиксированную ставку.
    """
    row = await pool.fetchrow(
        """
        UPDATE subscriptions SET end_date = $2, updated_at = now()
        WHERE id = $1 AND status = 'active'
        RETURNING id
        """,
        sub_id,
        end_date,
    )
    return row is not None


async def disable_subscription_via_expiry(pool: asyncpg.Pool, sub_id: int) -> int | None:
    """Ручное отключение подписки из веб-админки. Возвращает tg_id или None.

    Веб-процесс отдельный от бота и сам кикать из группы не может, поэтому ставим
    активной подписке `end_date = now()` — фоновая проверка окончаний бота
    (`run_expiry_check` → `expire_due_subscriptions`) на ближайшем проходе пометит
    её 'expired', кикнет из группы и уведомит пользователя (как при штатном
    окончании). `get_active_subscription` начинает возвращать None сразу.
    """
    row = await pool.fetchrow(
        """
        UPDATE subscriptions SET end_date = now(), updated_at = now()
        WHERE id = $1 AND status = 'active'
        RETURNING tg_id
        """,
        sub_id,
    )
    return row["tg_id"] if row is not None else None


# ── Кнопки меню бота (menu_buttons, этап 19) ──────────────────────────────────
async def get_menu_overrides(pool: asyncpg.Pool) -> dict[str, asyncpg.Record]:
    """Переопределения кнопок меню из БД: {key: record(label, is_visible)}.

    Дефолтные подписи/состав — в реестре services.menu; здесь только то, что
    админ изменил. Бот сливает их при рендере меню.
    """
    rows = await pool.fetch("SELECT key, label, is_visible FROM menu_buttons")
    return {r["key"]: r for r in rows}


async def upsert_menu_button(
    pool: asyncpg.Pool, key: str, label: str | None, is_visible: bool
) -> None:
    """Сохраняет переопределение кнопки меню (label=None → дефолт из реестра)."""
    await pool.execute(
        """
        INSERT INTO menu_buttons(key, label, is_visible, updated_at)
        VALUES($1, $2, $3, now())
        ON CONFLICT (key) DO UPDATE
            SET label = EXCLUDED.label, is_visible = EXCLUDED.is_visible,
                updated_at = now()
        """,
        key,
        label,
        is_visible,
    )


# ── Тексты экранов бота (screen_texts, этап 22) ───────────────────────────────
async def get_screen_overrides(pool: asyncpg.Pool) -> dict[str, dict]:
    """Переопределения экранов из БД: {key: {"body": str|None, "photo_url": str|None}}.

    Дефолтные тексты — в реестре services.screens; здесь только переопределения.
    Возвращаем ВСЕ строки (фото может быть задано при дефолтном тексте, тогда body=NULL),
    резолв «что показать» — на стороне services.screens.
    """
    rows = await pool.fetch("SELECT key, body, photo_url FROM screen_texts")
    return {r["key"]: {"body": r["body"], "photo_url": r["photo_url"]} for r in rows}


async def upsert_screen_text(pool: asyncpg.Pool, key: str, body: str | None) -> None:
    """Сохраняет переопределение текста экрана (body=None → дефолт из реестра).

    Картинку (photo_url) не трогаем — правки текста и фото независимы.
    """
    await pool.execute(
        """
        INSERT INTO screen_texts(key, body, updated_at)
        VALUES($1, $2, now())
        ON CONFLICT (key) DO UPDATE
            SET body = EXCLUDED.body, updated_at = now()
        """,
        key,
        body,
    )


async def upsert_screen_photo(pool: asyncpg.Pool, key: str, photo_url: str | None) -> None:
    """Сохраняет/снимает картинку экрана (photo_url=None → без фото).

    Текст (body) не трогаем — правки текста и фото независимы.
    """
    await pool.execute(
        """
        INSERT INTO screen_texts(key, photo_url, updated_at)
        VALUES($1, $2, now())
        ON CONFLICT (key) DO UPDATE
            SET photo_url = EXCLUDED.photo_url, updated_at = now()
        """,
        key,
        photo_url,
    )


# ── Реферальная программа (referral_links / referrals / bonus_ledger, этап 17) ─
async def get_or_create_referral_code(pool: asyncpg.Pool, tg_id: int, gen) -> str:
    """Реф-код пользователя (создаёт при первом обращении). gen — генератор кандидата.

    Коллизии кода крайне редки (8 символов из 31), но на всякий случай повторяем
    генерацию; гонку по tg_id (параллельное создание) разрешаем чтением существующего.
    """
    existing = await pool.fetchrow(
        "SELECT code FROM referral_links WHERE tg_id = $1", tg_id
    )
    if existing is not None:
        return existing["code"]
    for _ in range(10):
        code = gen()
        try:
            await pool.execute(
                "INSERT INTO referral_links(tg_id, code) VALUES($1, $2)", tg_id, code
            )
            return code
        except UniqueViolationError:
            row = await pool.fetchrow(
                "SELECT code FROM referral_links WHERE tg_id = $1", tg_id
            )
            if row is not None:  # код по tg_id уже создан параллельно
                return row["code"]
            # иначе коллизия самого кода — пробуем другой
    raise RuntimeError("не удалось сгенерировать уникальный реф-код")


async def get_referral_link_owner(pool: asyncpg.Pool, code: str) -> int | None:
    """tg_id владельца реф-кода (None — кода нет)."""
    row = await pool.fetchrow(
        "SELECT tg_id FROM referral_links WHERE code = $1", code
    )
    return row["tg_id"] if row is not None else None


async def is_newbie(pool: asyncpg.Pool, tg_id: int) -> bool:
    """Новичок = ещё ничего не покупал: ни подписки, ни оплаченного билета, ни платежа."""
    row = await pool.fetchrow(
        """
        SELECT NOT EXISTS(SELECT 1 FROM subscriptions WHERE tg_id = $1)
           AND NOT EXISTS(SELECT 1 FROM tickets WHERE tg_id = $1 AND status = 'paid')
           AND NOT EXISTS(SELECT 1 FROM payments WHERE tg_id = $1 AND status = 'succeeded')
           AS newbie
        """,
        tg_id,
    )
    return bool(row["newbie"])


async def get_referral_by_invitee(pool: asyncpg.Pool, invitee_tg_id: int) -> asyncpg.Record | None:
    """Реферальная связь, в которой пользователь — приглашённый (или None)."""
    return await pool.fetchrow(
        "SELECT * FROM referrals WHERE invitee_tg_id = $1", invitee_tg_id
    )


async def bind_referral(
    pool: asyncpg.Pool, referrer_tg_id: int, invitee_tg_id: int
) -> asyncpg.Record | None:
    """Фиксирует связь «пригласивший→новичок» (status='pending'). Идемпотентно.

    Возвращает созданную строку или None, если приглашённый уже привязан ранее
    (первая привязка побеждает — uniq invitee_tg_id).
    """
    return await pool.fetchrow(
        """
        INSERT INTO referrals(referrer_tg_id, invitee_tg_id)
        VALUES($1, $2)
        ON CONFLICT (invitee_tg_id) DO NOTHING
        RETURNING *
        """,
        referrer_tg_id,
        invitee_tg_id,
    )


async def qualify_referral(
    pool: asyncpg.Pool, *, invitee_tg_id: int, event_id: int | None,
    discount_amount: int, bonus_amount: int,
    category: str, accrue_after: datetime | None,
) -> asyncpg.Record | None:
    """Квалифицирует связь при первой покупке новичка (pending → qualified), этап 40.

    Идемпотентно: обновляет только связь в статусе 'pending'. Суммы фиксируются
    на момент покупки (последующая правка правил задним числом не влияет).
    `category` — категория покупки (banya/retreat/subscription/yoga/consult);
    `event_id` — только для билетов (иначе NULL); `accrue_after` — момент, с
    которого бонус можно начислять (дата события для билета, now() для покупок
    без даты). Возвращает обновлённую строку или None (связи нет / уже
    квалифицирована).
    """
    return await pool.fetchrow(
        """
        UPDATE referrals
        SET status = 'qualified', event_id = $2,
            discount_amount = $3, bonus_amount = $4, qualified_at = now(),
            category = $5, accrue_after = $6
        WHERE invitee_tg_id = $1 AND status = 'pending'
        RETURNING *
        """,
        invitee_tg_id,
        event_id,
        Decimal(discount_amount),
        Decimal(bonus_amount),
        category,
        accrue_after,
    )


# ── Правила реф-программы по категориям (этап 40) ─────────────────────────────
async def get_referral_rules(pool: asyncpg.Pool) -> dict[str, asyncpg.Record]:
    """Все правила реф-программы: {category: строка referral_rules}."""
    rows = await pool.fetch("SELECT * FROM referral_rules")
    return {r["category"]: r for r in rows}


async def get_referral_rule(pool: asyncpg.Pool, category: str) -> asyncpg.Record | None:
    """Правило одной категории (None — строки нет, применяются дефолты сервиса)."""
    return await pool.fetchrow(
        "SELECT * FROM referral_rules WHERE category = $1", category
    )


async def upsert_referral_rule(
    pool: asyncpg.Pool, category: str, *,
    discount_kind: str, discount_value: int, bonus_kind: str, bonus_value: int,
) -> None:
    """Сохраняет правило категории из веб-админки (тип значения + величина)."""
    await pool.execute(
        """
        INSERT INTO referral_rules(category, discount_kind, discount_value,
                                   bonus_kind, bonus_value, updated_at)
        VALUES($1, $2, $3, $4, $5, now())
        ON CONFLICT (category) DO UPDATE
        SET discount_kind = EXCLUDED.discount_kind,
            discount_value = EXCLUDED.discount_value,
            bonus_kind = EXCLUDED.bonus_kind,
            bonus_value = EXCLUDED.bonus_value,
            updated_at = now()
        """,
        category,
        discount_kind,
        Decimal(discount_value),
        bonus_kind,
        Decimal(bonus_value),
    )


async def bonus_balance(conn, tg_id: int) -> int:
    """Баланс бонусов пользователя (SUM(delta), ₽). conn — pool или соединение."""
    row = await conn.fetchrow(
        "SELECT COALESCE(SUM(delta), 0) AS bal FROM bonus_ledger WHERE tg_id = $1",
        tg_id,
    )
    return int(row["bal"])


async def bonus_overview(pool: asyncpg.Pool, tg_id: int) -> dict[str, int]:
    """Сводка бонусов для экрана «Мои бонусы» (этап 41).

    · `active`  — доступно сейчас (баланс = SUM(delta), с учётом списаний);
    · `pending` — скоро начислится: связи в статусе 'qualified', момент начисления
      которых ещё не наступил (билет ждёт даты события; 'void' и 'accrued' не в счёт);
    · `total`   — всего начислено за всё время (сумма положительных операций:
      реф-бонусы, ручные начисления, возвраты списанного).
    """
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COALESCE(SUM(delta), 0) FROM bonus_ledger WHERE tg_id = $1) AS active,
            (SELECT COALESCE(SUM(delta), 0) FROM bonus_ledger
              WHERE tg_id = $1 AND delta > 0) AS total,
            (SELECT COALESCE(SUM(bonus_amount), 0) FROM referrals
              WHERE referrer_tg_id = $1 AND status = 'qualified') AS pending
        """,
        tg_id,
    )
    return {
        "active": int(row["active"]),
        "pending": int(row["pending"]),
        "total": int(row["total"]),
    }


async def spend_bonuses(
    pool: asyncpg.Pool, *, tg_id: int, payment_id: int, amount: int
) -> bool:
    """Списывает `amount` бонусов под платёж (delta<0). Защита от овердрафта и дублей.

    Под advisory-локом по tg_id проверяет баланс и пишет строку reason='spend'
    (уникальный частичный индекс по payment_id не даёт списать дважды на один платёж).
    Возвращает True — списано; False — недостаточно бонусов или уже списано.
    """
    if amount <= 0:
        return False
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", tg_id)
            if await bonus_balance(conn, tg_id) < amount:
                return False
            row = await conn.fetchrow(
                """
                INSERT INTO bonus_ledger(tg_id, delta, reason, payment_id)
                VALUES($1, $2, 'spend', $3)
                ON CONFLICT (payment_id) WHERE reason = 'spend' DO NOTHING
                RETURNING id
                """,
                tg_id,
                Decimal(-amount),
                payment_id,
            )
            return row is not None


async def refund_bonuses(pool: asyncpg.Pool, payment_id: int) -> bool:
    """Возвращает списанные под платёж бонусы (reason='refund'), если платёж не прошёл.

    Идемпотентно: возвращает ровно раз и только если было списание под этот платёж.
    True — бонусы возвращены этим вызовом.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            spend = await conn.fetchrow(
                "SELECT tg_id, delta FROM bonus_ledger "
                "WHERE payment_id = $1 AND reason = 'spend'",
                payment_id,
            )
            if spend is None:
                return False
            already = await conn.fetchrow(
                "SELECT 1 FROM bonus_ledger WHERE payment_id = $1 AND reason = 'refund'",
                payment_id,
            )
            if already is not None:
                return False
            await conn.execute(
                "INSERT INTO bonus_ledger(tg_id, delta, reason, payment_id, note) "
                "VALUES($1, $2, 'refund', $3, 'возврат бонусов: платёж не прошёл')",
                spend["tg_id"],
                -spend["delta"],  # делаем delta положительной
                payment_id,
            )
            return True


async def accrue_referral_bonus(
    pool: asyncpg.Pool, referral_id: int
) -> asyncpg.Record | None:
    """Начисляет пригласившему бонус по квалифицированной связи (этап 17, джоб).

    Под блокировкой строки связи: только из 'qualified' → 'accrued', пишет
    bonus_ledger(reason='referral_bonus') идемпотентно (уникальный индекс по
    referral_id). Возвращает строку связи при начислении, иначе None.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            ref = await conn.fetchrow(
                "SELECT * FROM referrals WHERE id = $1 AND status = 'qualified' FOR UPDATE",
                referral_id,
            )
            if ref is None:
                return None
            inserted = await conn.fetchrow(
                """
                INSERT INTO bonus_ledger(tg_id, delta, reason, referral_id)
                VALUES($1, $2, 'referral_bonus', $3)
                ON CONFLICT (referral_id) WHERE reason = 'referral_bonus' DO NOTHING
                RETURNING id
                """,
                ref["referrer_tg_id"],
                ref["bonus_amount"],
                referral_id,
            )
            await conn.execute(
                "UPDATE referrals SET status = 'accrued', accrued_at = now() WHERE id = $1",
                referral_id,
            )
            return ref if inserted is not None else ref


async def referrals_due_for_accrual(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Квалифицированные связи, у которых наступил момент начисления (этап 40).

    Момент — `accrue_after`: для билетов это дата события (как было до этапа 40,
    COALESCE со `starts_at` подстраховывает строки без бэкфилла), для покупок без
    даты (подписка/йога/консультации) — момент оплаты, т.е. сразу.

    Анти-возврат: для билета бонус положен, только если билет приглашённого всё
    ещё оплачен (не возвращён). К покупкам без события проверка неприменима.
    """
    return await pool.fetch(
        """
        SELECT r.id, r.referrer_tg_id, r.invitee_tg_id, r.event_id, r.bonus_amount,
               r.category, r.accrue_after, e.starts_at, e.title
        FROM referrals r
        LEFT JOIN events e ON e.id = r.event_id
        WHERE r.status = 'qualified'
          AND COALESCE(r.accrue_after, e.starts_at) <= now()
          AND (
              r.event_id IS NULL
              OR EXISTS(
                  SELECT 1 FROM tickets t
                  WHERE t.tg_id = r.invitee_tg_id AND t.event_id = r.event_id
                    AND t.status = 'paid'
              )
          )
        ORDER BY r.id
        """
    )


async def void_referral(pool: asyncpg.Pool, referral_id: int) -> None:
    """Аннулирует связь (возврат до события и т.п.): бонус не начисляется."""
    await pool.execute(
        "UPDATE referrals SET status = 'void' WHERE id = $1 AND status = 'qualified'",
        referral_id,
    )


async def get_referral_chains(pool: asyncpg.Pool, limit: int = 200) -> list[asyncpg.Record]:
    """Цепочки приглашений для админки: кто кого привёл, статус, суммы, имена."""
    return await pool.fetch(
        """
        SELECT r.id, r.referrer_tg_id, r.invitee_tg_id, r.status,
               r.discount_amount, r.bonus_amount, r.created_at, r.qualified_at, r.accrued_at,
               ru.username AS referrer_username, ru.first_name AS referrer_name,
               iu.username AS invitee_username, iu.first_name AS invitee_name,
               e.title AS event_title
        FROM referrals r
        LEFT JOIN users ru ON ru.tg_id = r.referrer_tg_id
        LEFT JOIN users iu ON iu.tg_id = r.invitee_tg_id
        LEFT JOIN events e ON e.id = r.event_id
        ORDER BY r.id DESC
        LIMIT $1
        """,
        limit,
    )


async def add_bonus_manual(
    pool: asyncpg.Pool, *, tg_id: int, amount: int, note: str | None = None
) -> int:
    """Ручное начисление/списание бонусов из админки (delta может быть отрицательной).

    Возвращает новый баланс. Списание не уводит баланс в минус (страховка в вызывающем).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", tg_id)
            await conn.execute(
                "INSERT INTO bonus_ledger(tg_id, delta, reason, note) "
                "VALUES($1, $2, 'manual', $3)",
                tg_id,
                Decimal(amount),
                note,
            )
            return await bonus_balance(conn, tg_id)


# ── Рассылки (этап 26): очередь задач веб-админки, бот-джоб разбирает ─────────
async def create_broadcast(
    pool: asyncpg.Pool,
    *,
    audience: str,
    body: str | None,
    photos: list[dict],
    created_by: str | None,
) -> int:
    """Кладёт рассылку в очередь со статусом 'pending'. Возвращает id."""
    row = await pool.fetchrow(
        """
        INSERT INTO broadcasts(audience, body, photos, created_by)
        VALUES($1, $2, $3, $4)
        RETURNING id
        """,
        audience,
        body,
        json.dumps(photos or []),
        created_by,
    )
    return row["id"]


async def claim_pending_broadcast(pool: asyncpg.Pool) -> asyncpg.Record | None:
    """Атомарно забирает старейшую ожидающую рассылку (pending → sending).

    FOR UPDATE SKIP LOCKED — параллельные проходы не возьмут одну и ту же задачу.
    Возвращает запись (photos — JSON-строка, разбирать json.loads) или None.
    """
    return await pool.fetchrow(
        """
        UPDATE broadcasts SET status = 'sending', started_at = now()
        WHERE id = (
            SELECT id FROM broadcasts WHERE status = 'pending'
            ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
        )
        RETURNING *
        """
    )


async def set_broadcast_total(pool: asyncpg.Pool, broadcast_id: int, total: int) -> None:
    await pool.execute(
        "UPDATE broadcasts SET total = $2 WHERE id = $1", broadcast_id, total
    )


async def finish_broadcast(
    pool: asyncpg.Pool, broadcast_id: int, *, sent: int, blocked: int, failed: int
) -> None:
    await pool.execute(
        """
        UPDATE broadcasts
        SET status = 'done', sent = $2, blocked = $3, failed = $4, finished_at = now()
        WHERE id = $1
        """,
        broadcast_id,
        sent,
        blocked,
        failed,
    )


async def list_broadcasts(pool: asyncpg.Pool, limit: int = 50) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM broadcasts ORDER BY id DESC LIMIT $1", limit
    )
