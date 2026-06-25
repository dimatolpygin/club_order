"""Мост «покупатель → админы» (этап 21.1).

Менеджер пишет покупателю из веб-админки (доставляет бот). Ответ покупателя боту
этот роутер пересылает всем админам — чтобы переписку можно было вести и с теми, у
кого нет @username (прямая связь из Telegram-клиента по numeric id невозможна).

Срабатывает только на свободный текст ВНЕ любого FSM-сценария и только если с
покупателем открыта переписка (менеджер недавно ему писал — repo.has_manager_
conversation). Поэтому роутер регистрируется ПОСЛЕДНИМ и не мешает другим сценариям:
сейчас свободный текст вне сценариев никем не обрабатывается.
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import asyncpg

from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..services import app_settings

router = Router()


def _all_admin_ids() -> list[int]:
    return sorted(set(settings.admin_id_list) | app_settings.extra_admin_ids())


@router.message(F.text & ~F.text.startswith("/"))
async def forward_to_admins(
    message: Message, pool: asyncpg.Pool, state: FSMContext, bot: Bot
) -> None:
    # Только вне активного FSM-сценария (иначе это ввод для другого флоу).
    if await state.get_state() is not None:
        return
    user = message.from_user
    if user is None:
        return
    # Пересылаем только при открытой переписке (менеджер недавно писал покупателю).
    if not await repo.has_manager_conversation(pool, user.id):
        return

    text = message.text or ""
    await repo.log_inbound_manager_message(pool, user.id, text)
    titles = await repo.user_ticket_titles(pool, user.id)
    note = "; ".join(titles[:5]) if titles else ""
    payload = texts.manager_inbound_to_admins(
        user.first_name, user.username, user.id, text, note
    )
    delivered = 0
    for admin_id in _all_admin_ids():
        with suppress(Exception):
            await bot.send_message(admin_id, payload)
            delivered += 1
    logger.info(
        "✉️ Ответ покупателя @{} (id:{}) переслан {} админам",
        user.username or "—", user.id, delivered,
    )
    with suppress(Exception):
        await message.answer(
            "Сообщение передано организатору — скоро ответим."
        )
