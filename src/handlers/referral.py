"""Реферальная программа для бань (этап 17): пользовательский флоу.

`/ссылка` (и `/link`, и кнопка «Пригласить друга») выдаёт персональную реф-ссылку,
баланс бонусов и условия. Привязка новичка по deep-link обрабатывается в
handlers/start.py (там точка входа `/start ref_<code>`). Начисление бонуса
пригласившему — отложенный джоб (services.referral_jobs), оплата бонусами — в
флоу билета (handlers/events.py).
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import referral as ref
from ..services import referral_rules as ref_rules

router = Router()


async def _show_link(target: Message, bot: Bot, pool: asyncpg.Pool, tg_id: int) -> None:
    code = await repo.get_or_create_referral_code(pool, tg_id, ref.new_code)
    me = await bot.get_me()
    link = ref.deep_link(me.username, code)
    balance = await repo.bonus_balance(pool, tg_id)
    # Величина скидки — из правила опорной категории (баня); при оформлении
    # применится величина той категории, которую друг реально покупает (этап 40).
    rule = await repo.get_referral_rule(pool, ref_rules.CATEGORY_BANYA)
    await target.answer(
        texts.referral_link_screen(link, balance, ref_rules.discount_phrase(rule)),
        reply_markup=kb.referral_link_kb(link),
    )
    logger.info(
        f"🤖 Бот → @{target.chat.username or '—'}: реф-ссылка (код {code}, баланс {balance} ₽)"
    )


# `/ссылка` (кириллица не всегда распознаётся Telegram как команда-сущность,
# поэтому матчим по тексту) и латинский алиас `/link`.
@router.message(F.text.regexp(r"(?i)^/(ссылка|link)(@[A-Za-z0-9_]+)?\s*$"))
async def cmd_link(message: Message, bot: Bot, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    await repo.set_fsm_state(pool, u.id, "screen:referral")
    await _show_link(message, bot, pool, u.id)


@router.callback_query(F.data == kb.NAV_REFERRAL)
async def nav_referral(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:referral")
    # Экран ссылки отправляем новым сообщением (в нём deep-link для пересылки).
    with suppress(TelegramBadRequest):
        await cb.message.delete()
    await _show_link(cb.message, bot, pool, cb.from_user.id)
    await cb.answer()
