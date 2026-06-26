"""Хендлеры /start и /menu. Точка входа в навигацию бота."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import app_settings
from ..services import menu
from ..services import referral as ref
from ..services import screens

router = Router()


async def _try_bind_referral(pool: asyncpg.Pool, message: Message, code: str) -> None:
    """Привязывает новичка к пригласившему по реф-коду (этап 17). Тихо игнорирует не-кейсы.

    Привязываем, только если: код существует, это не сам пользователь, он ещё не
    привязан и он новичок (ничего не покупал). Иначе — без эффекта.
    """
    invitee = message.from_user.id
    referrer = await repo.get_referral_link_owner(pool, code)
    if referrer is None or referrer == invitee:
        return
    if await repo.get_referral_by_invitee(pool, invitee) is not None:
        return  # уже привязан раньше (первая привязка побеждает)
    if not await repo.is_newbie(pool, invitee):
        return  # скидка новичка — только тем, кто ещё ничего не покупал
    bound = await repo.bind_referral(pool, referrer, invitee)
    if bound is not None:
        sums = await app_settings.referral_sums(pool)
        await message.answer(texts.referral_bound(sums["newbie_discount"]))
        logger.info(
            f"🔗 Реферал: @{message.from_user.username or '—'} (id:{invitee}) "
            f"привязан к пригласившему id:{referrer} по коду {code}"
        )


@router.message(CommandStart())
async def cmd_start(
    message: Message, pool: asyncpg.Pool, state: FSMContext, command: CommandObject
) -> None:
    await state.clear()
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    # Реферальный deep-link: `/start ref_<code>` — привязываем новичка.
    code = ref.parse_start_payload(command.args)
    if code:
        await _try_bind_referral(pool, message, code)
    await repo.set_fsm_state(pool, u.id, "screen:start")
    subscribed = await repo.get_active_subscription(pool, u.id) is not None
    await message.answer(
        await screens.text(pool, "start"),
        reply_markup=await menu.welcome_kb(pool, subscribed),
    )
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
    subscribed = await repo.get_active_subscription(pool, u.id) is not None
    await message.answer(
        await screens.text(pool, "menu"),
        reply_markup=await menu.main_menu_kb(pool, subscribed),
    )
    logger.info(f"🤖 Бот → @{u.username or '—'}: главное меню /menu")
