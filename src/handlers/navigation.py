"""Навигация по экранам бота (callback-кнопки) + FSM-флоу поддержки.

Каждый переход фиксирует текущий экран пользователя в club_bot.fsm_states,
чтобы админ видел, где человек находится/застрял (этап 8).
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
import asyncpg

from .. import keyboards as kb
from .. import repo
from ..logger import logger
from ..services import app_settings
from ..services import menu
from ..services import screens

router = Router()


async def _show(
    cb: CallbackQuery,
    pool: asyncpg.Pool,
    screen: str,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Показывает экран (редактируя текущее сообщение) и фиксирует экран в БД."""
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:{screen}")
    with suppress(TelegramBadRequest):  # «message is not modified» — не критично
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: экран «{screen}»")


# ── Информационные экраны ────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_START)
async def nav_start(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await _show(cb, pool, "start", await screens.text(pool, "start"), await menu.welcome_kb(pool))


@router.callback_query(F.data == kb.NAV_ABOUT)
async def nav_about(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "about", await screens.text(pool, "about"), kb.about_kb())


@router.callback_query(F.data == kb.NAV_RULES)
async def nav_rules(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "rules", await screens.text(pool, "rules"), kb.rules_kb())


@router.callback_query(F.data == kb.NAV_MENU)
async def nav_menu(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await _show(cb, pool, "menu", await screens.text(pool, "menu"), await menu.main_menu_kb(pool))


@router.callback_query(F.data == kb.NAV_SUPPORT)
async def nav_support(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    # Раздел поддержки = кнопка-ссылка на аккаунт поддержки (ссылка из админки).
    url = await app_settings.support_url(pool)
    text = await screens.text(pool, "support" if url else "support_no_link")
    await _show(cb, pool, "support", text, kb.support_kb(url or None))


# NAV_JOIN/NAV_TARIFF — роутер tariffs (этап 2); NAV_MYSUB/NAV_RENEW — payment
# (этапы 3/5); NAV_PROMO — роутер promo (этап 7).
