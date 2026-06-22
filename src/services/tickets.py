"""Оркестрация продажи билетов на события (этап 14).

Переиспользует платёжный конвейер подписок: создаёт платёж ЮKassa (kind='ticket'),
а при подтверждении атомарно выдаёт билет с проверкой мест (repo.activate_ticket_payment).
sync_ticket_payment вызывается и фоновым поллером (через payments.poll_pending —
диспетчеризация по kind), и кнопкой «Проверить оплату».

Скидки подписчику (этап 15) и промокоды (этап 16) здесь пока не применяются —
билет оплачивается по полной цене типа из админки. Билет НЕ даёт доступ в группу.
"""
from __future__ import annotations

from decimal import Decimal

import asyncpg
from aiogram import Bot

from .. import repo, texts
from ..logger import logger
from ..utils import fmt_price
from . import events as ev
from .receipt import build_receipt
from .yookassa import create_payment, get_payment, new_idempotence_key


async def start_ticket_payment(
    pool: asyncpg.Pool,
    *,
    tg_id: int,
    event_id: int,
    ticket_type: str,
    return_url: str,
) -> tuple[str, dict | None]:
    """Создаёт платёж ЮKassa за билет. Перепроверяет наличие мест перед оплатой.

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

    amount = Decimal(str(prices[ticket_type]))
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
    )
    logger.info(
        f"🎟 Платёж за билет создан: tg_id={tg_id}, событие #{event_id}, "
        f"{ticket_type}, {fmt_price(amount)} ₽, yk_id={yk_id}"
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
