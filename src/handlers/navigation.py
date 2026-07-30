"""Навигация по экранам бота (callback-кнопки) + FSM-флоу поддержки.

Каждый переход фиксирует текущий экран пользователя в club_bot.fsm_states,
чтобы админ видел, где человек находится/застрял (этап 8).
"""
from __future__ import annotations

from aiogram import F, Router
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
    key: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Показывает экран (заменяя текущее сообщение) и фиксирует экран в БД.

    Резолвит текст+картинку (services.screens.resolve) и отдаёт безопасному рендеру —
    переходы экран-с-фото ↔ экран-без-фото не ломаются (см. screens.render).
    """
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:{screen}")
    view = await screens.resolve(pool, key)
    await screens.render(
        cb.message, text=view["text"], markup=markup,
        photo_url=view["photo_url"], edit=True,
    )
    await cb.answer()
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: экран «{screen}»")


# ── Информационные экраны ────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_START)
async def nav_start(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    subscribed = await repo.get_active_subscription(pool, cb.from_user.id) is not None
    await _show(cb, pool, "start", "start", await menu.welcome_kb(pool, subscribed))


@router.callback_query(F.data == kb.NAV_ABOUTMENU)
async def nav_aboutmenu(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await _show(cb, pool, "aboutmenu", "aboutmenu", await menu.aboutmenu_kb(pool))


@router.callback_query(F.data == kb.NAV_ABOUT)
async def nav_about(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "about", "about", kb.about_kb())


@router.callback_query(F.data == kb.NAV_RULES)
async def nav_rules(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "rules", "rules", kb.rules_kb())


@router.callback_query(F.data == kb.NAV_MENU)
async def nav_menu(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    # Раздел «Главное меню» убран как дубль приветствия (этап 38): и NAV_MENU, и
    # NAV_START ведут на один стартовый экран. Обработчик оставлен для старых
    # сообщений с кнопкой NAV_MENU в истории чатов.
    await state.clear()
    subscribed = await repo.get_active_subscription(pool, cb.from_user.id) is not None
    await _show(cb, pool, "start", "start", await menu.welcome_kb(pool, subscribed))


@router.callback_query(F.data == kb.NAV_SUPPORT)
async def nav_support(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    # Раздел поддержки = кнопка-ссылка на аккаунт поддержки (ссылка из админки).
    url = await app_settings.support_url(pool)
    key = "support" if url else "support_no_link"
    await _show(cb, pool, "support", key, kb.support_kb(url or None))


# NAV_JOIN/NAV_TARIFF — роутер tariffs (этап 2); NAV_MYSUB/NAV_RENEW — payment
# (этапы 3/5); NAV_PROMO — роутер promo (этап 7).
