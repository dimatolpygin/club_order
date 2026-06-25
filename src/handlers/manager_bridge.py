"""Мост «покупатель → админка» (этап 21.1).

Менеджер пишет покупателю из веб-админки (доставляет бот). Ответ покупателя боту
этот роутер сохраняет в переписку (`manager_messages`, direction='in', непрочитанным)
— менеджер читает и отвечает В САМОЙ ВЕБ-АДМИНКЕ (раздел «Билеты» → «Написать»), а не
в Telegram-аккаунте. В списке билетов у покупателя появляется пометка «новый ответ».

Срабатывает только на свободный текст ВНЕ любого FSM-сценария и только если с
покупателем открыта переписка (менеджер недавно ему писал — repo.has_manager_
conversation). Поэтому роутер регистрируется ПОСЛЕДНИМ и не мешает другим сценариям:
сейчас свободный текст вне сценариев никем не обрабатывается.
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import asyncpg

from .. import repo
from ..logger import logger

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def receive_reply(
    message: Message, pool: asyncpg.Pool, state: FSMContext
) -> None:
    # Только вне активного FSM-сценария (иначе это ввод для другого флоу).
    if await state.get_state() is not None:
        return
    user = message.from_user
    if user is None:
        return
    # Принимаем как ответ только при открытой переписке (менеджер недавно писал).
    if not await repo.has_manager_conversation(pool, user.id):
        return

    text = message.text or ""
    await repo.log_inbound_manager_message(pool, user.id, text)
    logger.info(
        "✉️ Ответ покупателя @{} (id:{}) сохранён в переписку (видно в админке)",
        user.username or "—", user.id,
    )
    with suppress(Exception):
        await message.answer("Сообщение передано организатору — скоро ответим.")
