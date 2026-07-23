"""Оркестрация платежей: создание платежа ЮKassa и активация подписки.

Поток:
  1. start_payment — посчитать сумму по текущей ставке, создать платёж в ЮKassa,
     сохранить строку payments (pending), вернуть ссылку на оплату.
  2. sync_payment — узнать статус платежа в ЮKassa; при succeeded атомарно
     активировать подписку (см. repo.activate_payment — без дублей) и уведомить
     пользователя ровно один раз; при canceled — пометить платёж отменённым.
sync_payment дёргается и фоновым поллером, и кнопкой «Проверить оплату».
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from redis.asyncio import Redis

from .. import keyboards as kb
from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..utils import fmt_price
from . import admin_alerts
from . import promo as promo_service
from . import referral_rules as ref_rules
from . import tariffs
from .receipt import build_receipt
from .referral_notify import qualify_and_notify
from .yookassa import YooKassaError, create_payment, get_payment, new_idempotence_key

# ЮKassa не принимает платёж на 0 ₽ — реф-скидка не может увести сумму ниже.
MIN_PAYMENT_AMOUNT = Decimal("1.00")


async def referral_discount_for_subscription(
    pool: asyncpg.Pool, tg_id: int, base_amount: Decimal
) -> int:
    """Скидка новичка по реф-ссылке на подписку, ₽ (0 — неприменимо), этап 40.

    Условия те же, что для билетов: пользователь привязан как приглашённый, связь
    ещё 'pending' (первая покупка), он всё ещё новичок. Величина — из правила
    категории 'subscription' (фиксированная сумма или процент от цены периода).
    Ограничиваем так, чтобы к оплате осталось не меньше 1 ₽: полностью бесплатную
    подписку выдаёт промокод, а не рефералка.
    """
    refr = await repo.get_referral_by_invitee(pool, tg_id)
    if refr is None or refr["status"] != "pending":
        return 0
    if not await repo.is_newbie(pool, tg_id):
        return 0
    rule = await repo.get_referral_rule(pool, ref_rules.CATEGORY_SUBSCRIPTION)
    discount = ref_rules.discount_for(rule, base_amount)
    ceiling = int(max(Decimal(str(base_amount)) - MIN_PAYMENT_AMOUNT, Decimal(0)))
    return min(discount, ceiling)


async def start_payment(
    pool: asyncpg.Pool,
    redis: Redis,
    *,
    tg_id: int,
    duration_id: int,
    return_url: str,
) -> dict | None:
    """Создаёт платёж ЮKassa под выбранную длительность. None — если нет ставки/длительности."""
    duration = await repo.get_duration(pool, duration_id)
    tier = await tariffs.get_current_tier(pool, redis)
    if duration is None or tier is None:
        return None

    months: int = duration["months"]
    unit: str = duration["unit"]
    monthly: Decimal = tier["monthly_price"]
    # Сумма к оплате — цена за период (матрица ступень×период), может отличаться
    # от ставка×значение. Фиксируем за пользователем именно МЕСЯЧНУЮ ставку (monthly)
    # — по ней пойдут продления; итоговая сумма покупки берётся из матрицы.
    amount = await tariffs.period_price(pool, redis, tier, months, unit)
    # Скидка новичка по реф-ссылке (этап 40): разовая, зафиксированную ставку
    # (monthly) не трогает — по ней пойдут продления уже без скидки.
    ref_discount = await referral_discount_for_subscription(pool, tg_id, amount)
    if ref_discount:
        amount = amount - Decimal(ref_discount)
    user = await repo.get_user(pool, tg_id)
    description = f"Подписка в клуб «11:11» — {texts.period_phrase(months, unit)}"
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "tier_id": str(tier["id"]),
        "months": str(months),
        "unit": unit,
        "duration_id": str(duration_id),
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
        tier_id=tier["id"],
        months=months,
        fixed_price=monthly,
        amount=amount,
        confirmation_url=confirmation_url,
        status=payment.get("status", "pending"),
        unit=unit,
    )
    ref_note = f", скидка новичка −{ref_discount} ₽" if ref_discount else ""
    logger.info(
        f"💳 Платёж создан: tg_id={tg_id}, {fmt_price(monthly)} ₽/мес × "
        f"{texts.period_phrase(months, unit)} = {fmt_price(amount)} ₽{ref_note}, yk_id={yk_id}"
    )
    return {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
        "monthly": monthly,
        "months": months,
        "referral_discount": ref_discount,
    }


async def start_renewal(
    pool: asyncpg.Pool,
    *,
    tg_id: int,
    duration_id: int,
    return_url: str,
) -> dict | None:
    """Создаёт платёж-продление по ЗАФИКСИРОВАННОЙ ставке активной подписки.

    В отличие от первичной покупки, цена считается строго как
    зафиксированная_ставка × месяцы (матрица tier_prices — это «текущее»
    ценообразование, а продление сохраняет ставку). tier_id и ставка берутся из
    активной подписки. None — если активной подписки/длительности нет.
    """
    sub = await repo.get_active_subscription(pool, tg_id)
    duration = await repo.get_duration(pool, duration_id)
    if sub is None or duration is None:
        return None

    months: int = duration["months"]
    unit: str = duration["unit"]
    monthly: Decimal = sub["fixed_price"]
    amount = monthly * months
    user = await repo.get_user(pool, tg_id)
    description = f"Продление подписки в клуб «11:11» — {texts.period_phrase(months, unit)}"
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "tier_id": str(sub["tier_id"]) if sub["tier_id"] is not None else "",
        "months": str(months),
        "unit": unit,
        "duration_id": str(duration_id),
        "kind": "renewal",
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
        tier_id=sub["tier_id"],
        months=months,
        fixed_price=monthly,
        amount=amount,
        confirmation_url=confirmation_url,
        status=payment.get("status", "pending"),
        kind="renewal",
        unit=unit,
    )
    logger.info(
        f"💳 Продление создано: tg_id={tg_id}, {fmt_price(monthly)} ₽/мес × "
        f"{texts.period_phrase(months, unit)} = {fmt_price(amount)} ₽, yk_id={yk_id}"
    )
    return {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
        "monthly": monthly,
        "months": months,
    }


async def start_promo_payment(
    pool: asyncpg.Pool,
    redis: Redis,
    *,
    tg_id: int,
    promo_id: int,
    duration_id: int,
    return_url: str,
) -> tuple[str, dict | None]:
    """Создаёт платёж по промокоду. Перепроверяет код (лимит/срок) перед оплатой.

    Возвращает (статус, данные):
      статус 'ok' + dict — платёж создан;
      статус not_found/expired/exhausted/already_used — код больше неприменим;
      статус 'no_tier' — нет активной ступени/длительности (мест нет).
    """
    promo = await repo.get_promo(pool, promo_id)
    now = datetime.now(timezone.utc)
    already = (
        await repo.user_redeemed_promo(pool, promo_id, tg_id)
        if promo is not None else False
    )
    status = promo_service.validate(promo, now=now, already_used=already)
    if status != promo_service.VALID:
        return status, None

    duration = await repo.get_duration(pool, duration_id)
    tier = await tariffs.get_current_tier(pool, redis)
    if duration is None or tier is None:
        return "no_tier", None

    months: int = duration["months"]
    unit: str = duration["unit"]
    tier_monthly: Decimal = tier["monthly_price"]
    period = await tariffs.period_price(pool, redis, tier, months, unit)
    pricing = promo_service.compute_pricing(
        promo, tier_monthly=tier_monthly, period_price=period, months=months
    )
    amount: Decimal = pricing["amount"]
    if amount <= 0:
        return "no_tier", None  # страховка: админ-валидация не даёт нулевую сумму

    # Скидка новичка по реф-ссылке и промокод НЕ суммируются — берём ту, что даёт
    # меньшую сумму (этапы 16/40). Если выигрывает рефералка, промокод НЕ расходуем
    # (останется у пользователя на будущее) и ставку фиксируем обычную, не спец.
    ref_discount = await referral_discount_for_subscription(pool, tg_id, period)
    use_referral = ref_discount > 0 and (period - Decimal(ref_discount)) < amount
    if use_referral:
        amount = period - Decimal(ref_discount)

    user = await repo.get_user(pool, tg_id)
    description = (
        f"Подписка в клуб «11:11» — {texts.period_phrase(months, unit)}"
        if use_referral else
        f"Подписка в клуб «11:11» по промокоду {promo['code']} — "
        f"{texts.period_phrase(months, unit)}"
    )
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "tier_id": str(tier["id"]),
        "months": str(months),
        "unit": unit,
        "duration_id": str(duration_id),
    }
    if not use_referral:
        metadata["promo_id"] = str(promo_id)
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
        tier_id=tier["id"],
        months=months,
        fixed_price=tier_monthly if use_referral else pricing["fixed_price"],
        amount=amount,
        confirmation_url=confirmation_url,
        status=payment.get("status", "pending"),
        unit=unit,
        promo_id=None if use_referral else promo_id,
    )
    if use_referral:
        logger.info(
            f"💳 Платёж создан со скидкой новичка (выгоднее промокода {promo['code']}): "
            f"tg_id={tg_id}, −{ref_discount} ₽ = {fmt_price(amount)} ₽, yk_id={yk_id}"
        )
    else:
        logger.info(
            f"💳 Платёж по промокоду {promo['code']} создан: tg_id={tg_id}, "
            f"спец {fmt_price(pricing['special_monthly'])} ₽/мес × "
            f"{texts.period_phrase(months, unit)} = {fmt_price(amount)} ₽, yk_id={yk_id}"
        )
    return "ok", {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
        "special_monthly": pricing["special_monthly"],
        "months": months,
        "referral_instead_of_promo": use_referral,
        "referral_discount": ref_discount if use_referral else 0,
    }


async def sync_payment(
    pool: asyncpg.Pool, bot: Bot, payment: asyncpg.Record
) -> tuple[str, asyncpg.Record | None]:
    """Сверяет один платёж с ЮKassa. Возвращает (статус, запись подписки|None).

    Статусы: 'succeeded' (подписка активна), 'pending' (ждём), 'canceled' (отменён).
    При первой успешной активации шлёт пользователю экран успеха.
    """
    yk_id = payment["yookassa_payment_id"]

    # Уже завершён в нашей БД — отдадим связанную подписку без обращения к API.
    if payment["status"] == "succeeded":
        sub = await repo.get_last_subscription(pool, payment["tg_id"])
        return "succeeded", sub
    if payment["status"] == "canceled":
        return "canceled", None

    try:
        data = await get_payment(yk_id)
    except YooKassaError:
        return "pending", None  # сеть недоступна — попробуем в следующий раз

    status = data.get("status")
    if status == "succeeded":
        sub_id, created = await repo.activate_payment(pool, yk_id)
        if sub_id is None:
            return "pending", None
        sub = await pool.fetchrow("SELECT * FROM subscriptions WHERE id = $1", sub_id)
        if created:
            logger.info(
                f"✅ Подписка #{sub_id} активирована оплатой (tg_id={payment['tg_id']}, "
                f"yk_id={yk_id})"
            )
            await _notify_success(bot, payment["tg_id"], sub)
            # Уведомление админам о продаже (этап 42) — сбой не влияет на активацию.
            with suppress(Exception):
                await admin_alerts.subscription_paid(
                    pool, bot, tg_id=payment["tg_id"], payment=payment, subscription=sub
                )
            # Первая покупка подписки новичком квалифицирует реф-связь (этап 40).
            # У подписки нет даты события → бонус пригласившему начисляется сразу.
            # Продление не трогаем: связь к тому моменту давно не 'pending'.
            if payment["kind"] != "renewal":
                await qualify_and_notify(
                    pool, bot,
                    invitee_tg_id=payment["tg_id"],
                    category=ref_rules.CATEGORY_SUBSCRIPTION,
                    purchase_title="подписку в клуб «11:11»",
                    paid_amount=payment["amount"],
                )
        return "succeeded", sub

    if status in ("canceled", "cancelled"):
        await repo.mark_payment_canceled(pool, yk_id)
        logger.info(f"🚫 Платёж отменён: tg_id={payment['tg_id']}, yk_id={yk_id}")
        return "canceled", None

    return "pending", None


def add_chat_button(b: InlineKeyboardBuilder) -> None:
    """Кнопка перехода в закрытый чат (если инвайт-ссылка задана в настройках).

    Авто-одобрение заявки только у оплативших добавится на этапе 4 — пока ссылка
    просто ведёт в группу (заявка может ждать одобрения).
    """
    if settings.club_chat_invite_url:
        b.row(InlineKeyboardButton(
            text="Перейти в закрытый чат", url=settings.club_chat_invite_url
        ))


def success_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    add_chat_button(b)
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=kb.NAV_MYSUB))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=kb.NAV_START))
    return b


async def _notify_success(bot: Bot, tg_id: int, sub: asyncpg.Record | None) -> None:
    if sub is None:
        return
    text = texts.pay_success(
        fmt_price(sub["fixed_price"]),
        sub["start_date"],
        sub["end_date"],
    )
    try:
        await bot.send_message(tg_id, text, reply_markup=success_kb().as_markup())
    except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
        logger.warning(f"Не удалось уведомить tg_id={tg_id} об активации: {e}")


async def poll_pending(pool: asyncpg.Pool, bot: Bot) -> None:
    """Фоновый проход поллера по всем pending-платежам.

    Диспетчеризация по kind: билеты (kind='ticket') синкаются через
    services.tickets, подписки/продления/промо — через sync_payment.
    """
    from . import tickets as tickets_service

    pending = await repo.get_pending_payments(pool)
    if not pending:
        return
    logger.info(f"🔄 Поллер: проверяю {len(pending)} pending-платеж(ей)")
    for p in pending:
        try:
            if p["kind"] == "ticket":
                await tickets_service.sync_ticket_payment(pool, bot, p)
            else:
                await sync_payment(pool, bot, p)
        except Exception as e:  # noqa: BLE001 — один платёж не должен ронять цикл
            logger.error(f"Поллер: ошибка по yk_id={p['yookassa_payment_id']}: {e}")
