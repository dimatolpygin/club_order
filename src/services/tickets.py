"""Оркестрация продажи билетов на события (этап 14).

Переиспользует платёжный конвейер подписок: создаёт платёж ЮKassa (kind='ticket'),
а при подтверждении атомарно выдаёт билет с проверкой мест (repo.activate_ticket_payment).
sync_ticket_payment вызывается и фоновым поллером (через payments.poll_pending —
диспетчеризация по kind), и кнопкой «Проверить оплату».

Скидка подписчику (этап 15) и промокод (этап 16) НЕ суммируются — берётся
максимальная (меньшая итоговая цена, `ev.best_ticket_price`). На билетах работают
только `percent`-промокоды; активация промокода расходуется только если он реально
выиграл у скидки подписчика. Билет НЕ даёт доступ в группу.
"""
from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from aiogram import Bot

from .. import repo, texts
from ..logger import logger
from ..utils import fmt_price
from . import events as ev
from . import promo as promo_service
from .receipt import build_receipt
from .yookassa import create_payment, get_payment, new_idempotence_key


async def _promo_percent(
    pool: asyncpg.Pool, promo_id: int | None, tg_id: int
) -> tuple[int, asyncpg.Record | None]:
    """Процент скидки действующего percent-промокода для этого юзера (этап 16).

    Ревалидирует код в момент оплаты (источник истины). Возвращает (pct, promo):
    pct=0, если промокода нет, он невалиден, исчерпан/просрочен, уже использован
    этим юзером или имеет тип `fixed_price` (на билеты не распространяется).
    """
    if promo_id is None:
        return 0, None
    promo = await repo.get_promo(pool, promo_id)
    if promo is None or promo["kind"] != promo_service.KIND_PERCENT:
        return 0, None
    already = await repo.user_redeemed_promo(pool, promo_id, tg_id)
    status = promo_service.validate(
        promo, now=datetime.now(timezone.utc), already_used=already
    )
    if status != promo_service.VALID:
        return 0, None
    return int(promo["value"]), promo


async def start_ticket_payment(
    pool: asyncpg.Pool,
    *,
    tg_id: int,
    event_id: int,
    ticket_type: str,
    return_url: str,
    promo_id: int | None = None,
) -> tuple[str, dict | None]:
    """Создаёт платёж ЮKassa за билет. Перепроверяет наличие мест перед оплатой.

    Применяет лучшую из скидок (подписчик vs промокод, НЕ суммируются —
    `ev.best_ticket_price`). promo_id привязывается к платежу только если промокод
    реально выиграл (тогда при выдаче билета расходуется его активация).

    Возвращает (статус, данные):
      'ok' + dict   — платёж создан (payment_id, confirmation_url, amount);
      'invalid'     — событие/тип билета недоступны (нет цены, событие скрыто);
      'no_seats'    — мест нужного типа не осталось.
    """
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        return "invalid", None

    prices = await repo.get_event_prices(pool, event_id)
    if ticket_type not in prices:
        return "invalid", None

    counts = await repo.get_event_ticket_counts(pool, event_id)
    occupied = ev.seats_occupied(counts)
    if not ev.has_seats(event, ticket_type, occupied):
        return "no_seats", None

    # Скидка участника клуба: активная подписка 11:11 + процент события (этап 15).
    # Источник истины для суммы платежа — проверка подписки здесь и сейчас.
    is_subscriber = await repo.get_active_subscription(pool, tg_id) is not None
    subscriber_pct = event["subscriber_discount_percent"] if is_subscriber else 0
    # Промокод (этап 16): процент действующего percent-кода; макс. скидка не суммируется.
    promo_pct, promo = await _promo_percent(pool, promo_id, tg_id)
    amount, applied = ev.best_ticket_price(
        prices[ticket_type], subscriber_pct=subscriber_pct, promo_pct=promo_pct
    )
    # Промокод привязываем к платежу только если он реально выиграл — иначе активация
    # не расходуется (скидка подписчика дала ту же или большую выгоду).
    applied_promo_id = promo_id if applied == "promo" else None
    discount_pct = promo_pct if applied == "promo" else (
        subscriber_pct if applied == "subscriber" else 0
    )
    user = await repo.get_user(pool, tg_id)
    description = (
        f"Билет «{ev.ticket_label(ticket_type)}» на «{event['title']}»"
    )
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "kind": "ticket",
        "event_id": str(event_id),
        "ticket_type": ticket_type,
    }
    if applied_promo_id is not None:
        metadata["promo_id"] = str(applied_promo_id)
    payment = await create_payment(
        amount=amount,
        description=description,
        return_url=return_url,
        metadata=metadata,
        receipt=receipt,
        idempotence_key=idem,
    )
    yk_id = payment["id"]
    confirmation_url = (payment.get("confirmation") or {}).get("confirmation_url")
    await repo.create_payment(
        pool,
        yookassa_payment_id=yk_id,
        idempotence_key=idem,
        tg_id=tg_id,
        tier_id=None,
        months=1,
        fixed_price=amount,
        amount=amount,
        confirmation_url=confirmation_url,
        status=payment.get("status", "pending"),
        kind="ticket",
        event_id=event_id,
        ticket_type=ticket_type,
        promo_id=applied_promo_id,
    )
    if applied == "promo":
        disc_note = f", промокод {promo['code']} −{discount_pct}%"
    elif applied == "subscriber":
        disc_note = f", скидка подписчику {discount_pct}%"
    else:
        disc_note = ""
    logger.info(
        f"🎟 Платёж за билет создан: tg_id={tg_id}, событие #{event_id}, "
        f"{ticket_type}, {fmt_price(amount)} ₽{disc_note}, yk_id={yk_id}"
    )
    return "ok", {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
    }


async def sync_ticket_payment(
    pool: asyncpg.Pool, bot: Bot, payment: asyncpg.Record, *, notify: bool = True
) -> tuple[str, asyncpg.Record | None]:
    """Сверяет платёж за билет с ЮKassa. Возвращает (статус, запись билета|None).

    Статусы: 'succeeded' (билет выдан), 'pending', 'canceled', 'no_seats'
    (мест не хватило — деньги к ручному возврату), 'no_event' (событие удалено).

    notify=True (поллер) — при первой выдаче/невыдаче шлёт пользователю сообщение.
    notify=False (ручная «Проверить оплату») — push не шлём, экран рисует хендлер
    редактированием текущего сообщения (без дубля).
    """
    yk_id = payment["yookassa_payment_id"]

    if payment["status"] == "succeeded":
        ticket = (
            await repo.get_ticket(pool, payment["ticket_id"])
            if payment["ticket_id"] is not None else None
        )
        return "succeeded", ticket
    if payment["status"] == "canceled":
        return "canceled", None
    if payment["status"] == "refund_due":
        return "no_seats", None

    from .yookassa import YooKassaError
    try:
        data = await get_payment(yk_id)
    except YooKassaError:
        return "pending", None

    status = data.get("status")
    if status == "succeeded":
        ticket_id, created, reason = await repo.activate_ticket_payment(pool, yk_id)
        if reason in ("no_seats", "no_event"):
            logger.warning(
                f"🎟 Билет не выдан ({reason}): tg_id={payment['tg_id']}, yk_id={yk_id} "
                f"— платёж к ручному возврату"
            )
            if notify:
                await _notify_ticket_failed(bot, payment["tg_id"], reason)
            return reason, None
        if ticket_id is None:
            return "pending", None
        ticket = await repo.get_ticket(pool, ticket_id)
        if created and notify:
            event = await repo.get_event(pool, payment["event_id"])
            logger.info(
                f"✅ Билет #{ticket_id} выдан (tg_id={payment['tg_id']}, yk_id={yk_id})"
            )
            await _notify_ticket_success(bot, payment["tg_id"], ticket, event)
        elif created:
            logger.info(
                f"✅ Билет #{ticket_id} выдан (tg_id={payment['tg_id']}, yk_id={yk_id})"
            )
        return "succeeded", ticket

    if status in ("canceled", "cancelled"):
        await repo.mark_payment_canceled(pool, yk_id)
        logger.info(f"🚫 Платёж за билет отменён: tg_id={payment['tg_id']}, yk_id={yk_id}")
        return "canceled", None

    return "pending", None


async def _notify_ticket_success(
    bot: Bot, tg_id: int, ticket: asyncpg.Record | None, event: asyncpg.Record | None
) -> None:
    if ticket is None or event is None:
        return
    from .. import keyboards as kb

    text = texts.ticket_success(
        event["title"], ev.ticket_label(ticket["ticket_type"]),
        event["starts_at"], event["rules_text"],
    )
    try:
        await bot.send_message(
            tg_id, text, reply_markup=kb.ticket_rules_kb(ticket["id"])
        )
    except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
        logger.warning(f"Не удалось отправить билет tg_id={tg_id}: {e}")


async def _notify_ticket_failed(bot: Bot, tg_id: int, reason: str) -> None:
    from .. import keyboards as kb

    text = texts.TICKET_NO_EVENT if reason == "no_event" else texts.TICKET_SOLD_DURING
    try:
        await bot.send_message(tg_id, text, reply_markup=kb.to_menu_kb())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Не удалось уведомить tg_id={tg_id} о невыдаче билета: {e}")
