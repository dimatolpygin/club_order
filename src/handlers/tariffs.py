"""Экран выбора тарифа: ступень → длительность → сводка к оплате.

Кнопки строятся из БД (сервис tariffs). Ступени с исчерпанным лимитом мест
не показываются. Сумма = помесячная ставка × число месяцев.
Кнопка «Перейти к оплате» на этапе 2 — заглушка (реальная оплата на этапе 3).
"""
from __future__ import annotations

from contextlib import suppress
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
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


# ── Шаг 1: список доступных ступеней ─────────────────────────────────────────
@router.callback_query(F.data.in_({kb.NAV_JOIN, kb.NAV_TARIFF}))
async def show_tariffs(
    cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis
) -> None:
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:tariffs")
    tiers = await tariffs.get_available_tiers(pool, redis)

    if not tiers:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: тарифы (мест нет)")
        return

    b = InlineKeyboardBuilder()
    for t in tiers:
        seats = "" if t["seats_left"] is None else f" · осталось {t['seats_left']}"
        b.row(
            kb.InlineKeyboardButton(
                text=f"{t['name']} — {fmt_price(t['monthly_price'])} ₽/мес{seats}",
                callback_data=f"tier:{t['id']}",
            )
        )
    b.row(kb.InlineKeyboardButton(text="Назад", callback_data=kb.NAV_START))
    await _edit(cb, texts.TARIFF_CHOOSE, b.as_markup())
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: показал {len(tiers)} тариф(ов)"
    )


# ── Шаг 2: выбор длительности для ступени ────────────────────────────────────
@router.callback_query(F.data.startswith("tier:"))
async def show_durations(
    cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis
) -> None:
    tier_id = int(cb.data.split(":", 1)[1])
    tier = await repo.get_tier(pool, tier_id)
    if tier is None or not tier["is_active"]:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:tariff_duration:{tier_id}")
    durations = await tariffs.get_available_durations(pool, redis)
    monthly = tier["monthly_price"]

    b = InlineKeyboardBuilder()
    for d in durations:
        months = d["months"]
        total = Decimal(monthly) * months
        b.row(
            kb.InlineKeyboardButton(
                text=f"{months} мес — {fmt_price(total)} ₽",
                callback_data=f"buy:{tier_id}:{d['id']}",
            )
        )
    b.row(kb.InlineKeyboardButton(text="Назад", callback_data=kb.NAV_TARIFF))
    await _edit(
        cb,
        texts.tariff_duration_title(tier["name"], fmt_price(monthly)),
        b.as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: длительности тарифа «{tier['name']}»"
    )


# ── Шаг 3: сводка к оплате (кнопка оплаты — заглушка до этапа 3) ──────────────
@router.callback_query(F.data.startswith("buy:"))
async def show_summary(
    cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis
) -> None:
    _, tier_id_s, dur_id_s = cb.data.split(":")
    tier = await repo.get_tier(pool, int(tier_id_s))
    duration = await repo.get_duration(pool, int(dur_id_s))
    if tier is None or duration is None or not tier["is_active"]:
        await _edit(cb, texts.TARIFF_NONE, kb.to_menu_kb())
        return

    months = duration["months"]
    monthly = tier["monthly_price"]
    total = Decimal(monthly) * months
    await repo.set_fsm_state(
        pool, cb.from_user.id, f"screen:tariff_summary:{tier['id']}:{months}m"
    )

    b = InlineKeyboardBuilder()
    # Заглушка оплаты — заменяется реальной кнопкой ЮKassa на этапе 3.
    b.row(kb.InlineKeyboardButton(text="Перейти к оплате", callback_data="pay:soon"))
    b.row(kb.InlineKeyboardButton(text="Назад", callback_data=f"tier:{tier['id']}"))
    await _edit(
        cb,
        texts.tariff_summary(tier["name"], fmt_price(monthly), months, fmt_price(total)),
        b.as_markup(),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: сводка {tier['name']} × {months} мес = {fmt_price(total)} ₽"
    )


@router.callback_query(F.data == "pay:soon")
async def pay_soon(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await cb.answer("Оплата подключается на следующем этапе.", show_alert=True)
