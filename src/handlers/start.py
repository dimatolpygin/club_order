"""Хендлеры /start и /menu. Точка входа в навигацию бота."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    await repo.set_fsm_state(pool, u.id, "screen:start")
    await message.answer(texts.WELCOME, reply_markup=kb.welcome_kb())
    logger.info(f"🤖 Бот → @{u.username or '—'}: приветствие /start")


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    u = message.from_user
    lines = [f"Ваш Telegram ID: <code>{u.id}</code>"]
    if message.chat.type != "private":
        lines.append(f"ID этого чата: <code>{message.chat.id}</code>")
    await message.answer("\n".join(lines))
    logger.info(f"🤖 Бот → @{u.username or '—'}: /id ({u.id})")


@router.message(Command("menu"))
async def cmd_menu(message: Message, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    await repo.set_fsm_state(pool, u.id, "screen:menu")
    await message.answer(texts.MAIN_MENU, reply_markup=kb.main_menu_kb())
    logger.info(f"🤖 Бот → @{u.username or '—'}: главное меню /menu")
