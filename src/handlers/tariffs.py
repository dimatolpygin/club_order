"""Экран подписки: пользователь видит только длительности с ценой.

Помесячная ставка определяется автоматически движком (services.tariffs.get_current_tier)
по числу занятых мест — ступени пользователю не показываются. Сумма = ставка × месяцы.
Кнопка «Перейти к оплате» на этапе 2 — заглушка (реальная оплата на этапе 3).
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import tariffs
from ..utils import fmt_price

router = Router()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    with suppress(TelegramBadRequest):
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ── Экран выбора длительности (цена — текущая ставка) ────────────────────────
@router.callback_query(F.data.in_({kb.NAV_JOIN, kb.NAV_TARIFF}))
async def show_tariffs(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    # Уже оплатившим не показываем выбор тарифа — ведём в «Мою подписку».
    if await repo.get_active_subscription(pool, cb.from_user.id) is not None:
        from .payment import render_my_subscription

        await render_my_subscription(cb, pool)
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:tariffs")
    tier = await tariffs.get_current_tier(pool, redis)
    if tier is None:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: подписка (мест нет)")
        return

    monthly = tier["monthly_price"]
    durations = await tariffs.get_active_durations(pool, redis)
    prices = await tariffs.prices_for(pool, redis, tier, durations)

    b = InlineKeyboardBuilder()
    for d in durations:
        total = prices[d["id"]]
        b.row(
            InlineKeyboardButton(
                text=f"{d['months']} {texts.period_short(d['unit'])} — {fmt_price(total)} ₽",
                callback_data=f"buy:{d['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="Ввести промокод", callback_data=kb.NAV_PROMO))
    b.row(InlineKeyboardButton(text="Назад", callback_data=kb.NAV_START))
    await _edit(cb, texts.tariff_choose(fmt_price(monthly)), b.as_markup())
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: подписка, ставка {fmt_price(monthly)} ₽/мес "
        f"(ступень #{tier['tier_index']}), {len(durations)} длит."
    )


# ── Сводка к оплате (кнопка оплаты — заглушка до этапа 3) ─────────────────────
@router.callback_query(F.data.startswith("buy:"))
async def show_summary(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    duration = await repo.get_duration(pool, int(cb.data.split(":", 1)[1]))
    tier = await tariffs.get_current_tier(pool, redis)
    if duration is None or tier is None:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        return

    months = duration["months"]
    unit = duration["unit"]
    total = await tariffs.period_price(pool, redis, tier, months, unit)
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:summary:{months}{unit}")

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Перейти к оплате", callback_data=f"pay:create:{duration['id']}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data=kb.NAV_TARIFF))
    await _edit(
        cb,
        texts.tariff_summary(months, unit, fmt_price(total)),
        b.as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: сводка {texts.period_phrase(months, unit)} "
        f"= {fmt_price(total)} ₽"
    )
