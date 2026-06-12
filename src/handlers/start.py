"""Хендлер /start. Этап 0 — заглушка: фиксируем пользователя и отвечаем приветствием."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
import asyncpg

from .. import repo, texts
from ..logger import logger

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, pool: asyncpg.Pool) -> None:
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    await message.answer(texts.START_STUB)
    logger.info(f"🤖 Бот → @{u.username or '—'}: приветствие (заглушка этапа 0)")
