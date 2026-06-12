"""Авто-приём заявок в закрытую группу (этап 4).

Бот — админ супергруппы с правом одобрять заявки. На каждую заявку (chat_join_request)
проверяет активную подписку пользователя: есть → approve + «доступ открыт»;
нет → decline + пояснение. Если подписка есть, но approve упал технически —
шлёт экран «не удалось добавить» с переходом в поддержку.

Инвайт-ссылка группы должна быть с включённой «заявкой на вступление»
(creates_join_request), иначе апдейт chat_join_request не приходит.
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatJoinRequest, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..config import settings
from ..logger import logger

router = Router()


def _granted_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if settings.club_chat_invite_url:
        b.row(InlineKeyboardButton(text="Перейти в чат", url=settings.club_chat_invite_url))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=kb.NAV_MYSUB))
    return b


def _denied_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Оформить подписку", callback_data=kb.NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=kb.NAV_SUPPORT))
    return b


def _failed_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Написать в поддержку", callback_data=kb.NAV_SUPPORT))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=kb.NAV_MYSUB))
    return b


async def _notify(bot: Bot, user_id: int, text: str, markup) -> None:
    """Сообщение пользователю (он мог не открывать ЛС бота — тогда тихо пропускаем)."""
    with suppress(Exception):
        await bot.send_message(user_id, text, reply_markup=markup)


@router.chat_join_request()
async def on_join_request(
    request: ChatJoinRequest, bot: Bot, pool: asyncpg.Pool
) -> None:
    chat_id = request.chat.id
    user = request.from_user

    # Обрабатываем только заявки в нашу группу (если id задан в настройках).
    club_id = settings.club_chat_id_int
    if club_id is not None and chat_id != club_id:
        return

    sub = await repo.get_active_subscription(pool, user.id)
    uname = user.username or "—"

    if sub is None:
        with suppress(TelegramBadRequest):
            await request.decline()
        await _notify(bot, user.id, texts.ACCESS_DENIED, _denied_kb().as_markup())
        logger.info(
            f"🚫 Заявка отклонена: @{uname} (id:{user.id}) — нет активной подписки"
        )
        return

    try:
        await request.approve()
    except TelegramBadRequest as e:
        # Напр. бот не админ / нет права одобрять / пользователь уже в чате.
        await _notify(bot, user.id, texts.ACCESS_FAILED, _failed_kb().as_markup())
        logger.error(f"⚠️ Не удалось одобрить заявку @{uname} (id:{user.id}): {e}")
        return

    await _notify(bot, user.id, texts.ACCESS_GRANTED, _granted_kb().as_markup())
    logger.info(f"✅ Заявка одобрена: @{uname} (id:{user.id}) — подписка активна")
