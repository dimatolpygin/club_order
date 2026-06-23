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
from decimal import Decimal

import asyncpg
from aiogram import Bot

from .. import repo, texts
from ..logger import logger
from ..utils import fmt_price
from . import app_settings
from . import events as ev
from . import promo as promo_service
from .receipt import build_receipt
from .yookassa import create_payment, get_payment, new_idempotence_key


async def _referral_discount(pool: asyncpg.Pool, tg_id: int, event, newbie_discount: int) -> int:
    """Скидка новичка по реф-ссылке на баню, ₽ (0 — неприменимо) (этап 17).

    Действует только: событие — баня; пользователь привязан как приглашённый и
    связь ещё 'pending' (первая покупка); пользователь всё ещё новичок.
    """
    if event["kind"] != ev.KIND_BANYA:
        return 0
    refr = await repo.get_referral_by_invitee(pool, tg_id)
    if refr is None or refr["status"] != "pending":
        return 0
    if not await repo.is_newbie(pool, tg_id):
        return 0
    return newbie_discount


async def compute_ticket_pricing(
    pool: asyncpg.Pool, *, tg_id: int, event, ticket_type: str,
    base_price, promo_id: int | None = None, use_bonus: bool = False,
) -> dict:
    """Единый расчёт цены билета (скидки + бонусы) — источник истины для показа и оплаты.

    Скидки (подписчик/промокод/новичок) НЕ суммируются — берётся максимальная
    (`ev.best_ticket_price`). Бонусы добивают цену уже со скидкой, но не более 50%
    (`ev.bonus_cap`). Возвращает поля для рендера сводки и для создания платежа.
    """
    is_subscriber = await repo.get_active_subscription(pool, tg_id) is not None
    subscriber_pct = event["subscriber_discount_percent"] if is_subscriber else 0
    promo_pct, promo = await _promo_percent(pool, promo_id, tg_id)
    sums = await app_settings.referral_sums(pool)
    referral_amount = await _referral_discount(pool, tg_id, event, sums["newbie_discount"])

    price, applied = ev.best_ticket_price(
        base_price, subscriber_pct=subscriber_pct, promo_pct=promo_pct,
        referral_amount=referral_amount,
    )
    applied_promo_id = promo_id if applied == "promo" else None
    discount_pct = (
        promo_pct if applied == "promo"
        else subscriber_pct if applied == "subscriber" else 0
    )
    balance = await repo.bonus_balance(pool, tg_id)
    cap = ev.bonus_cap(price, balance)
    bonus_used = cap if (use_bonus and cap > 0) else 0
    final = price - Decimal(bonus_used)
    return {
        "base_price": Decimal(str(base_price)),
        "price_after_discount": price,
        "applied": applied,
        "discount_pct": discount_pct,
        "promo": promo,
        "applied_promo_id": applied_promo_id,
        "referral_amount": referral_amount,
        "balance": balance,
        "bonus_cap": cap,
        "bonus_used": bonus_used,
        "final": final,
    }


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
    use_bonus: bool = False,
) -> tuple[str, dict | None]:
    """Создаёт платёж ЮKassa за билет. Перепроверяет наличие мест перед оплатой.

    Скидки (подписчик/промокод/новичок) НЕ суммируются — берётся максимальная;
    бонусы добивают цену до −50%. promo_id привязывается к платежу только если
    промокод реально выиграл. Бонусы списываются под платёж (`spend_bonuses`,
    защита от овердрафта); при срыве платежа возвращаются (`refund_bonuses`).

    Возвращает (статус, данные):
      'ok' + dict     — платёж создан (payment_id, confirmation_url, amount);
      'invalid'       — событие/тип билета недоступны (нет цены, событие скрыто);
      'no_seats'      — мест нужного типа не осталось;
      'free'          — цена со скидкой 0 ₽ (оплата не нужна — редкий кейс, в поддержку);
      'bonus_failed'  — не удалось списать бонусы (баланс изменился) — повторить.
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

    pr = await compute_ticket_pricing(
        pool, tg_id=tg_id, event=event, ticket_type=ticket_type,
        base_price=prices[ticket_type], promo_id=promo_id, use_bonus=use_bonus,
    )
    amount: Decimal = pr["final"]
    applied = pr["applied"]
    bonus_used = pr["bonus_used"]
    # Скидка увела цену в 0 без бонусов — ЮKassa не примет нулевой платёж.
    if amount <= 0:
        return "free", None

    user = await repo.get_user(pool, tg_id)
    description = f"Билет «{ev.ticket_label(ticket_type)}» на «{event['title']}»"
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "kind": "ticket",
        "event_id": str(event_id),
        "ticket_type": ticket_type,
    }
    if pr["applied_promo_id"] is not None:
        metadata["promo_id"] = str(pr["applied_promo_id"])
    if bonus_used:
        metadata["bonus_used"] = str(bonus_used)
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
    payment_db_id = await repo.create_payment(
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
        promo_id=pr["applied_promo_id"],
    )
    # Списываем бонусы под платёж (под advisory-локом; защита от овердрафта/дублей).
    if bonus_used:
        ok = await repo.spend_bonuses(
            pool, tg_id=tg_id, payment_id=payment_db_id, amount=bonus_used
        )
        if not ok:
            await repo.mark_payment_canceled(pool, yk_id)
            logger.warning(
                f"🎟 Не удалось списать {bonus_used} бонусов (tg_id={tg_id}, yk_id={yk_id}) "
                f"— платёж отменён"
            )
            return "bonus_failed", None

    disc_map = {
        "promo": f", промокод {pr['promo']['code']} −{pr['discount_pct']}%" if pr["promo"] else "",
        "subscriber": f", скидка подписчику {pr['discount_pct']}%",
        "referral": f", скидка новичка {pr['referral_amount']} ₽",
        "none": "",
    }
    bonus_note = f", бонусами −{bonus_used} ₽" if bonus_used else ""
    logger.info(
        f"🎟 Платёж за билет создан: tg_id={tg_id}, событие #{event_id}, "
        f"{ticket_type}, {fmt_price(amount)} ₽{disc_map.get(applied, '')}{bonus_note}, "
        f"yk_id={yk_id}"
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
            # Билет не выдан — деньги к ручному возврату, бонусы возвращаем сразу.
            await repo.refund_bonuses(pool, payment["id"])
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
        if created:
            event = await repo.get_event(pool, payment["event_id"])
            # Первая покупка бани новичком квалифицирует реф-связь (бонус — после события).
            await _qualify_referral_after_purchase(pool, payment["tg_id"], event)
            logger.info(
                f"✅ Билет #{ticket_id} выдан (tg_id={payment['tg_id']}, yk_id={yk_id})"
            )
            if notify:
                await _notify_ticket_success(bot, payment["tg_id"], ticket, event)
        return "succeeded", ticket

    if status in ("canceled", "cancelled"):
        await repo.mark_payment_canceled(pool, yk_id)
        # Платёж не прошёл — возвращаем списанные под него бонусы (идемпотентно).
        if await repo.refund_bonuses(pool, payment["id"]):
            logger.info(f"↩️ Бонусы возвращены: платёж отменён (yk_id={yk_id})")
        logger.info(f"🚫 Платёж за билет отменён: tg_id={payment['tg_id']}, yk_id={yk_id}")
        return "canceled", None

    return "pending", None


async def _qualify_referral_after_purchase(pool: asyncpg.Pool, tg_id: int, event) -> None:
    """Квалифицирует реф-связь при первой покупке бани новичком (этап 17).

    Идемпотентно (repo.qualify_referral обновляет только 'pending'). Суммы скидки/
    бонуса фиксируются на момент покупки. Бонус пригласившему начислит джоб после даты.
    """
    if event is None or event["kind"] != ev.KIND_BANYA:
        return
    sums = await app_settings.referral_sums(pool)
    row = await repo.qualify_referral(
        pool, invitee_tg_id=tg_id, event_id=event["id"],
        discount_amount=sums["newbie_discount"], bonus_amount=sums["referrer_bonus"],
    )
    if row is not None:
        logger.info(
            f"🔗 Реферал квалифицирован: invitee={tg_id}, событие #{event['id']}; "
            f"бонус {sums['referrer_bonus']} ₽ пригласившему id={row['referrer_tg_id']} "
            f"после {event['starts_at']:%d.%m.%Y}"
        )


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
