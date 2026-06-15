"""Слой доступа к данным. Все таблицы — в схеме club_bot (search_path задан в db.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

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
    """Добавляет/включает длительность (значение + единица). months хранит значение."""
    await pool.execute(
        """
        INSERT INTO durations(months, unit, sort_order, is_active)
        VALUES($1, $2, $1, $3)
        ON CONFLICT (months, unit) DO UPDATE SET is_active = EXCLUDED.is_active
        """,
        value,
        unit,
        is_active,
    )


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
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO payments(
            yookassa_payment_id, idempotence_key, tg_id, tier_id, months, unit,
            fixed_price, amount, confirmation_url, status, kind, promo_id
        )
        VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
    )
    return row["id"]


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
            sub = await conn.fetchrow(
                """
                INSERT INTO subscriptions(
                    tg_id, tier_id, fixed_price, months, unit, end_date, source, status
                )
                VALUES($1, $2, $3, $4, $5, $6, $7, 'active')
                RETURNING id
                """,
                pay["tg_id"],
                pay["tier_id"],
                pay["fixed_price"],
                months,
                unit,
                add_period(now, months, unit),
                source,
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
        SELECT s.id, s.tg_id, s.end_date, s.fixed_price, s.unit,
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
