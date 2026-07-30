"""Продажа услуг «по количеству» без даты/мест: йога, консультации (этапы 46/47).

Услуга — НЕ событие: нет даты, мест и счётчика остатка. Пользователь выбирает
продукт категории (йога: индивидуальное/групповое) и количество; сумма = цена
продукта × количество. После оплаты услуга НЕ выдаёт билет и доступ в группу —
пользователь получает контакт менеджера (@zhannazlotnikova ведёт запись в личке).

Переиспользует платёжный конвейер: создаёт платёж ЮKassa (`kind='service'`), а при
подтверждении лишь фиксирует оплату (`repo.activate_service_payment` — без выдачи
билета), после чего начисляет рефералку (сразу — у услуги нет даты события),
уведомляет админов (этап 42) и шлёт пользователю контакт менеджера.

Скидки: скидка подписчику (процент на продукт) и скидка новичка по реф-ссылке НЕ
суммируются — берётся максимальная (`ev.best_ticket_price`, как у билетов). Промокоды
и бонусы к услугам подключим на этапе 47 (для йоги решением раунда 4 они не нужны).
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
from aiogram import Bot

from .. import repo
from ..logger import logger
from ..utils import fmt_price
from . import admin_alerts
from . import events as ev
from . import referral_rules as ref_rules
from .receipt import build_receipt
from .referral_notify import qualify_and_notify
from .yookassa import create_payment, get_payment, new_idempotence_key

# Разумный предел количества за одну покупку (защита от опечаток/абьюза).
MAX_QUANTITY = 99


async def _referral_discount(
    pool: asyncpg.Pool, tg_id: int, category: str, base_price
) -> int:
    """Скидка новичка по реф-ссылке на услугу, ₽ (0 — неприменимо), этап 40.

    Условия те же, что для билетов/подписки: пользователь привязан как приглашённый,
    связь ещё 'pending' (первая покупка), он всё ещё новичок. Величина — из правила
    категории услуги ('yoga'/'consult'): фиксированная сумма или процент от цены.
    """
    refr = await repo.get_referral_by_invitee(pool, tg_id)
    if refr is None or refr["status"] != "pending":
        return 0
    if not await repo.is_newbie(pool, tg_id):
        return 0
    rule = await repo.get_referral_rule(pool, category)
    return ref_rules.discount_for(rule, base_price)


async def compute_service_pricing(
    pool: asyncpg.Pool, *, tg_id: int, product, quantity: int
) -> dict:
    """Единый расчёт цены услуги (источник истины для показа и оплаты).

    База = цена продукта × количество. Скидка подписчику (процент продукта) и
    скидка новичка (реф-ссылка) НЕ суммируются — берётся максимальная.
    """
    base = Decimal(str(product["price"])) * quantity
    is_subscriber = await repo.get_active_subscription(pool, tg_id) is not None
    subscriber_pct = product["subscriber_discount_percent"] if is_subscriber else 0
    referral_amount = await _referral_discount(pool, tg_id, product["category"], base)

    price, applied = ev.best_ticket_price(
        base, subscriber_pct=subscriber_pct, promo_pct=0, referral_amount=referral_amount,
    )
    return {
        "base_price": base,
        "price_after_discount": price,
        "applied": applied,
        "subscriber_pct": subscriber_pct,
        "referral_amount": referral_amount,
        "final": price,
    }


async def start_service_payment(
    pool: asyncpg.Pool, *, tg_id: int, product_id: int, quantity: int, return_url: str,
) -> tuple[str, dict | None]:
    """Создаёт платёж ЮKassa за услугу. Возвращает (статус, данные):

      'ok' + dict — платёж создан (payment_id, confirmation_url, amount, quantity, title);
      'invalid'   — продукт недоступен (выключен, нет цены) или количество вне 1..MAX;
      'free'      — цена со скидкой 0 ₽ (оплата не нужна — редкий кейс, в поддержку).
    """
    product = await repo.get_service_product(pool, product_id)
    if product is None or not product["is_active"] or product["price"] <= 0:
        return "invalid", None
    if not (1 <= quantity <= MAX_QUANTITY):
        return "invalid", None

    pr = await compute_service_pricing(pool, tg_id=tg_id, product=product, quantity=quantity)
    amount: Decimal = pr["final"]
    if amount <= 0:
        return "free", None

    user = await repo.get_user(pool, tg_id)
    description = f"{product['title']} × {quantity}"
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "kind": "service",
        "category": product["category"],
        "product_code": product["code"],
        "product_id": str(product_id),
        "quantity": str(quantity),
    }
    payment = await create_payment(
        amount=amount, description=description, return_url=return_url,
        metadata=metadata, receipt=receipt, idempotence_key=idem,
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
        kind="service",
        service_product_id=product_id,
        quantity=quantity,
    )
    disc = ""
    if pr["applied"] == "subscriber":
        disc = f", скидка участника −{pr['subscriber_pct']}%"
    elif pr["applied"] == "referral":
        disc = f", скидка новичка −{pr['referral_amount']} ₽"
    logger.info(
        f"🧘 Платёж за услугу создан: tg_id={tg_id}, «{product['title']}» × {quantity}, "
        f"{fmt_price(amount)} ₽{disc}, yk_id={yk_id}"
    )
    return "ok", {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
        "quantity": quantity,
        "title": product["title"],
    }


async def sync_service_payment(
    pool: asyncpg.Pool, bot: Bot, payment: asyncpg.Record, *, notify: bool = True
) -> tuple[str, dict | None]:
    """Сверяет платёж услуги с ЮKassa. Возвращает (статус, данные|None).

    Статусы: 'succeeded' (оплата зафиксирована), 'pending', 'canceled'.
    При первой фиксации: рефералка (сразу — даты нет), уведомление админам,
    сообщение пользователю с контактом менеджера.

    notify=True (поллер) — шлём push пользователю; notify=False (ручная проверка) —
    экран рисует хендлер редактированием текущего сообщения (без дубля).
    """
    yk_id = payment["yookassa_payment_id"]

    if payment["status"] == "succeeded":
        return "succeeded", await _paid_data(pool, payment)
    if payment["status"] == "canceled":
        return "canceled", None

    from .yookassa import YooKassaError
    try:
        data = await get_payment(yk_id)
    except YooKassaError:
        return "pending", None

    status = data.get("status")
    if status == "succeeded":
        created = await repo.activate_service_payment(pool, yk_id)
        paid = await _paid_data(pool, payment)
        product = paid["product"] if paid else None
        if created:
            logger.info(
                f"✅ Услуга оплачена (tg_id={payment['tg_id']}, yk_id={yk_id})"
            )
            if product is not None:
                # Первая покупка новичком квалифицирует реф-связь; у услуги нет даты
                # события → бонус пригласившему начисляется сразу (этап 40).
                await qualify_and_notify(
                    pool, bot,
                    invitee_tg_id=payment["tg_id"],
                    category=product["category"],
                    purchase_title=f"«{product['title']}»",
                    paid_amount=payment["amount"],
                )
                # Уведомление админам (этап 42) — сбой не должен влиять на оплату.
                with suppress(Exception):
                    await admin_alerts.service_sold(
                        pool, bot, tg_id=payment["tg_id"], product=product,
                        quantity=payment["quantity"], amount=payment["amount"],
                    )
            if notify:
                await _notify_service_success(pool, bot, payment["tg_id"], paid)
        return "succeeded", paid

    if status in ("canceled", "cancelled"):
        await repo.mark_payment_canceled(pool, yk_id)
        logger.info(f"🚫 Платёж за услугу отменён: tg_id={payment['tg_id']}, yk_id={yk_id}")
        return "canceled", None

    return "pending", None


async def _paid_data(pool: asyncpg.Pool, payment: asyncpg.Record) -> dict | None:
    """Данные для экрана «услуга оплачена»: продукт, количество, сумма."""
    if payment["service_product_id"] is None:
        return None
    product = await repo.get_service_product(pool, payment["service_product_id"])
    if product is None:
        return None
    return {"product": product, "quantity": payment["quantity"], "amount": payment["amount"]}


async def _notify_service_success(
    pool: asyncpg.Pool, bot: Bot, tg_id: int, paid: dict | None
) -> None:
    if paid is None:
        return
    from .. import keyboards as kb
    from .. import texts
    from . import app_settings

    url = await app_settings.manager_url(pool)
    text = texts.service_success(
        paid["product"]["title"], paid["quantity"], fmt_price(paid["amount"]),
    )
    try:
        await bot.send_message(tg_id, text, reply_markup=kb.service_paid_kb(url))
    except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
        logger.warning(f"Не удалось отправить контакт менеджера tg_id={tg_id}: {e}")
