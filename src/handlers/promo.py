"""Пользовательский флоу промокодов (этап 7).

NAV_PROMO → ввод кода (FSM) → валидация. Валидный код открывает экран со
спец-ценой и выбором срока; кнопка ведёт к оплате по промокоду (платёж создаётся
с привязкой promo_id, активация учитывает применение). Невалидный код даёт
корректное сообщение (не найден / истёк / исчерпан / уже использован).
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import payments, promo as promo_service, tariffs
from ..states import PromoStates
from ..utils import fmt_price
from .payment import _pay_kb, _return_url

router = Router()

# Сообщение + клавиатура на каждый невалидный статус.
_FAIL_SCREENS = {
    promo_service.NOT_FOUND: (texts.PROMO_NOT_FOUND, kb.promo_not_found_kb),
    promo_service.EXPIRED: (texts.PROMO_EXPIRED, kb.promo_failed_kb),
    promo_service.EXHAUSTED: (texts.PROMO_EXHAUSTED, kb.promo_failed_kb),
    promo_service.ALREADY_USED: (texts.PROMO_ALREADY_USED, kb.promo_failed_kb),
}


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    # Текущее сообщение может быть фото (инфо-экран с картинкой, этап 37): по фото
    # edit_text невозможен — заменяем сообщение (удаляем и шлём заново).
    if cb.message.photo:
        with suppress(TelegramBadRequest):
            await cb.message.delete()
        await cb.message.answer(text, reply_markup=markup)
    else:
        with suppress(TelegramBadRequest):  # «message is not modified» — не критично
            await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ── Ввод промокода ────────────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_PROMO)
async def nav_promo(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_code)
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:promo")
    await _edit(cb, texts.PROMO_ENTER, kb.promo_enter_kb())
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: ввод промокода")


async def _applied_keyboard(
    pool: asyncpg.Pool, redis: Redis, promo: asyncpg.Record
) -> tuple[InlineKeyboardMarkup | None, "object"]:
    """Клавиатура экрана «промокод применён»: сроки со спец-ценой. None — мест нет."""
    tier = await tariffs.get_current_tier(pool, redis)
    if tier is None:
        return None, None
    durations = await tariffs.get_active_durations(pool, redis)
    normal = await tariffs.prices_for(pool, redis, tier, durations)
    b = InlineKeyboardBuilder()
    for d in durations:
        pricing = promo_service.compute_pricing(
            promo,
            tier_monthly=tier["monthly_price"],
            period_price=normal[d["id"]],
            months=d["months"],
        )
        b.row(InlineKeyboardButton(
            text=f"{d['months']} {texts.period_short(d['unit'])} — "
                 f"{fmt_price(pricing['amount'])} ₽",
            callback_data=f"promo:buy:{promo['id']}:{d['id']}",
        ))
    b.row(InlineKeyboardButton(text="Выбрать обычный тариф", callback_data=kb.NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Назад", callback_data=kb.NAV_MENU))
    return b.as_markup(), tier


@router.message(PromoStates.waiting_code)
async def promo_code_entered(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    code = promo_service.normalize_code(message.text)
    promo = await repo.get_promo_by_code(pool, code) if code else None
    now = datetime.now(timezone.utc)
    already = (
        await repo.user_redeemed_promo(pool, promo["id"], message.from_user.id)
        if promo is not None else False
    )
    status = promo_service.validate(promo, now=now, already_used=already)

    if status != promo_service.VALID:
        await state.clear()
        text, kb_factory = _FAIL_SCREENS[status]
        await message.answer(text, reply_markup=kb_factory())
        logger.info(
            f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» — {status}"
        )
        return

    markup, tier = await _applied_keyboard(pool, redis, promo)
    if markup is None:
        await state.clear()
        await message.answer(texts.TARIFF_NONE, reply_markup=kb.to_menu_kb())
        return

    await state.clear()
    special = promo_service.compute_pricing(
        promo, tier_monthly=tier["monthly_price"],
        period_price=tier["monthly_price"], months=1,
    )["special_monthly"]
    await repo.set_fsm_state(pool, message.from_user.id, "screen:promo:applied")
    await message.answer(
        texts.promo_applied(fmt_price(special), promo["fixes_price"]),
        reply_markup=markup,
    )
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» применён, "
        f"спец {fmt_price(special)} ₽/мес"
    )


# ── Оплата по промокоду ───────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("promo:buy:"))
async def promo_buy(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool, redis: Redis) -> None:
    _, _, promo_id, dur_id = cb.data.split(":")
    await cb.answer("Создаю платёж...")
    status, result = await payments.start_promo_payment(
        pool, redis,
        tg_id=cb.from_user.id,
        promo_id=int(promo_id),
        duration_id=int(dur_id),
        return_url=await _return_url(bot),
    )
    if status in _FAIL_SCREENS:
        text, kb_factory = _FAIL_SCREENS[status]
        await _edit(cb, text, kb_factory())
        return
    if status != "ok" or result is None:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:pay:pending")
    await _edit(
        cb,
        texts.pay_created(fmt_price(result["amount"])),
        _pay_kb(result["confirmation_url"], result["payment_id"]).as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: ссылка на оплату по промокоду "
        f"{fmt_price(result['amount'])} ₽ (yk_id={result['payment_id']})"
    )
