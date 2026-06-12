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
from ..utils import add_months, fmt_price
from . import tariffs
from .receipt import build_receipt
from .yookassa import YooKassaError, create_payment, get_payment, new_idempotence_key


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
    monthly: Decimal = tier["monthly_price"]
    amount = monthly * months
    user = await repo.get_user(pool, tg_id)
    description = f"Подписка в клуб «11:11» — {months} мес"
    receipt = build_receipt(user, description, amount)
    idem = new_idempotence_key()
    metadata = {
        "tg_id": str(tg_id),
        "tier_id": str(tier["id"]),
        "months": str(months),
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
    )
    logger.info(
        f"💳 Платёж создан: tg_id={tg_id}, {fmt_price(monthly)} ₽/мес × {months} мес "
        f"= {fmt_price(amount)} ₽, yk_id={yk_id}"
    )
    return {
        "payment_id": yk_id,
        "confirmation_url": confirmation_url,
        "amount": amount,
        "monthly": monthly,
        "months": months,
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
        end_date = add_months(datetime.now(timezone.utc), payment["months"])
        sub_id, created = await repo.activate_payment(pool, yk_id, end_date)
        if sub_id is None:
            return "pending", None
        sub = await pool.fetchrow("SELECT * FROM subscriptions WHERE id = $1", sub_id)
        if created:
            logger.info(
                f"✅ Подписка #{sub_id} активирована оплатой (tg_id={payment['tg_id']}, "
                f"yk_id={yk_id})"
            )
            await _notify_success(bot, payment["tg_id"], sub)
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
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=kb.NAV_MENU))
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
    """Фоновый проход поллера по всем pending-платежам."""
    pending = await repo.get_pending_payments(pool)
    if not pending:
        return
    logger.info(f"🔄 Поллер: проверяю {len(pending)} pending-платеж(ей)")
    for p in pending:
        try:
            await sync_payment(pool, bot, p)
        except Exception as e:  # noqa: BLE001 — один платёж не должен ронять цикл
            logger.error(f"Поллер: ошибка по yk_id={p['yookassa_payment_id']}: {e}")
