"""Экраны оплаты ЮKassa и «Моя подписка» (этап 3).

Поток: сводка → «Перейти к оплате» (pay:create) создаёт платёж и показывает экран
с ссылкой на оплату → «Проверить оплату» (pay:check) сверяет статус немедленно.
Параллельно фоновый поллер сам активирует подписку (см. services.payments).
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import keyboards as kb
from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..services import payments
from ..services.yookassa import YooKassaError
from ..utils import fmt_price

router = Router()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    with suppress(TelegramBadRequest):
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


async def _return_url(bot: Bot) -> str:
    """Куда ЮKassa вернёт пользователя: настройка или ссылка на бота."""
    if settings.yookassa_return_url:
        return settings.yookassa_return_url
    me = await bot.me()
    return f"https://t.me/{me.username}"


def _pay_kb(confirmation_url: str | None, yk_id: str) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if confirmation_url:
        b.row(InlineKeyboardButton(text="Оплатить", url=confirmation_url))
    b.row(InlineKeyboardButton(text="Проверить оплату", callback_data=f"pay:check:{yk_id}"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data=kb.NAV_TARIFF))
    return b


# ── Создание платежа ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("pay:create:"))
async def pay_create(
    cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool, redis: Redis
) -> None:
    duration_id = int(cb.data.rsplit(":", 1)[1])
    await cb.answer("Создаю платёж...")
    try:
        result = await payments.start_payment(
            pool, redis,
            tg_id=cb.from_user.id,
            duration_id=duration_id,
            return_url=await _return_url(bot),
        )
    except YooKassaError:
        await _edit(cb, texts.PAY_CREATE_FAILED, kb.to_menu_kb())
        return
    if result is None:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:pay:pending")
    await _edit(
        cb,
        texts.pay_created(fmt_price(result["amount"])),
        _pay_kb(result["confirmation_url"], result["payment_id"]).as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: ссылка на оплату "
        f"{fmt_price(result['amount'])} ₽ (yk_id={result['payment_id']})"
    )


# ── Проверка оплаты вручную ──────────────────────────────────────────────────
@router.callback_query(F.data.startswith("pay:check:"))
async def pay_check(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 2)[2]
    payment = await repo.get_payment_by_yk_id(pool, yk_id)
    if payment is None:
        await cb.answer("Платёж не найден.", show_alert=True)
        return

    status, sub = await payments.sync_payment(pool, bot, payment)
    if status == "succeeded" and sub is not None:
        await repo.set_fsm_state(pool, cb.from_user.id, "screen:pay:success")
        await _edit(
            cb,
            texts.pay_success(
                fmt_price(sub["fixed_price"]), sub["start_date"], sub["end_date"]
            ),
            payments.success_kb().as_markup(),
        )
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: оплата подтверждена")
    elif status == "canceled":
        await repo.set_fsm_state(pool, cb.from_user.id, "screen:pay:canceled")
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="Попробовать снова", callback_data=kb.NAV_TARIFF))
        b.row(InlineKeyboardButton(text="Поддержка", callback_data=kb.NAV_SUPPORT))
        await _edit(cb, texts.PAY_CANCELED, b.as_markup())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: платёж отменён")
    else:
        await cb.answer(texts.PAY_STILL_PENDING, show_alert=True)


# ── Моя подписка ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_MYSUB)
async def my_subscription(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:mysub")
    sub = await repo.get_active_subscription(pool, cb.from_user.id)
    if sub is None:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="Оформить подписку", callback_data=kb.NAV_JOIN))
        b.row(InlineKeyboardButton(text="Ввести промокод", callback_data=kb.NAV_PROMO))
        b.row(InlineKeyboardButton(text="В главное меню", callback_data=kb.NAV_MENU))
        await _edit(cb, texts.MY_SUB_NONE, b.as_markup())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: моя подписка — нет активной")
        return

    days_left = (sub["end_date"] - datetime.now(timezone.utc)).days
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Продлить подписку", callback_data=kb.NAV_RENEW))
    b.row(InlineKeyboardButton(text="Правила клуба", callback_data=kb.NAV_RULES))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=kb.NAV_MENU))
    await _edit(
        cb,
        texts.my_sub_active(
            fmt_price(sub["fixed_price"]),
            sub["start_date"],
            sub["end_date"],
            texts.days_left_phrase(days_left),
        ),
        b.as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: моя подписка активна "
        f"(осталось {days_left} дн.)"
    )
