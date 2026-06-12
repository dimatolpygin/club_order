"""Навигация по экранам бота (callback-кнопки) + FSM-флоу поддержки.

Каждый переход фиксирует текущий экран пользователя в club_bot.fsm_states,
чтобы админ видел, где человек находится/застрял (этап 8).
"""
from __future__ import annotations

from contextlib import suppress
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..states import SupportStates

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
    await _show(cb, pool, "start", texts.WELCOME, kb.welcome_kb())


@router.callback_query(F.data == kb.NAV_ABOUT)
async def nav_about(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "about", texts.ABOUT, kb.about_kb())


@router.callback_query(F.data == kb.NAV_RULES)
async def nav_rules(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    await _show(cb, pool, "rules", texts.RULES, kb.rules_kb())


@router.callback_query(F.data == kb.NAV_MENU)
async def nav_menu(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await _show(cb, pool, "menu", texts.MAIN_MENU, kb.main_menu_kb())


@router.callback_query(F.data == kb.NAV_SUPPORT)
async def nav_support(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()  # выходим из возможного ожидания ввода
    await _show(cb, pool, "support", texts.SUPPORT, kb.support_kb())


# ── Заглушки разделов следующих этапов (оплата/подписка/промокоды) ────────────
# NAV_JOIN/NAV_TARIFF обрабатывает роутер tariffs (этап 2).
@router.callback_query(F.data.in_({kb.NAV_MYSUB, kb.NAV_RENEW, kb.NAV_PROMO}))
async def nav_soon(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    screen = (cb.data or "nav:?").split(":", 1)[1]
    await _show(cb, pool, f"soon:{screen}", texts.SOON, kb.to_menu_kb())


# ── Поддержка: выбор темы → ожидание текста обращения ────────────────────────
_SUPPORT_PROMPTS = {
    kb.SUP_PAYMENT: ("payment", texts.SUPPORT_PAYMENT),
    kb.SUP_NOACCESS: ("noaccess", texts.SUPPORT_NOACCESS),
    kb.SUP_QUESTION: ("question", texts.SUPPORT_QUESTION),
    kb.SUP_ADMIN: ("admin", texts.SUPPORT_ADMIN),
}


@router.callback_query(F.data.in_(set(_SUPPORT_PROMPTS)))
async def support_topic(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    topic, prompt = _SUPPORT_PROMPTS[cb.data]
    await state.set_state(SupportStates.waiting_message)
    await state.update_data(topic=topic)
    await repo.set_fsm_state(pool, cb.from_user.id, f"support:waiting:{topic}")
    with suppress(TelegramBadRequest):
        await cb.message.edit_text(prompt, reply_markup=kb.back_to_support_kb())
    await cb.answer()
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: поддержка «{topic}», жду сообщение")


@router.message(SupportStates.waiting_message)
async def support_receive(
    message: Message, bot: Bot, pool: asyncpg.Pool, state: FSMContext
) -> None:
    data = await state.get_data()
    topic = data.get("topic", "—")
    u = message.from_user

    # Пересылаем обращение всем админам.
    header = (
        f"🆘 <b>Обращение в поддержку</b> ({escape(topic)})\n"
        f"От: @{escape(u.username or '—')} (id:<code>{u.id}</code>, {escape(u.first_name or '')})\n\n"
    )
    body = escape(message.text or "(без текста / медиа)")
    for admin_id in settings.admin_id_list:
        with suppress(Exception):
            await bot.send_message(admin_id, header + body)

    await state.clear()
    await repo.set_fsm_state(pool, u.id, "support:sent")
    await message.answer(texts.SUPPORT_SENT, reply_markup=kb.to_menu_kb())
    logger.info(
        f"🤖 Бот → @{u.username or '—'}: обращение «{topic}» передано "
        f"{len(settings.admin_id_list)} админам"
    )
