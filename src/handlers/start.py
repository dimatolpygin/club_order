"""Хендлеры /start и /menu. Точка входа в навигацию бота."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, URLInputFile
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import consent
from ..services import menu
from ..services import referral as ref
from ..services import referral_rules as ref_rules
from ..services import screens

router = Router()


async def _needs_pd_consent(pool: asyncpg.Pool, tg_id: int) -> bool:
    """Нужно ли показать экран согласия на обработку ПД (этап 49)."""
    return not await repo.has_pd_consent(pool, tg_id, consent.PD_CONSENT_VERSION)


async def _show_consent(message: Message, pool: asyncpg.Pool, tg_id: int, username: str | None) -> None:
    """Показывает экран согласия на обработку ПД (документы + текст «Политики» + «Согласен»).

    Сначала бот присылает прикреплённые в админке документы (оферта, политика и т.п.)
    отдельными файлами, затем текст согласия с кнопкой «Согласен». Текст-только (без
    картинки): «Политика» может быть длинной, лимит подписи под фото (1024) тут неуместен.
    Текст и документы берутся из реестра экранов (правятся в веб-админке).
    """
    await repo.set_fsm_state(pool, tg_id, "screen:pd_consent")
    view = await screens.resolve(pool, "pd_consent")
    for doc in view.get("documents") or []:
        url, name = doc.get("url"), doc.get("name")
        if not url:
            continue
        try:
            await message.answer_document(URLInputFile(url, filename=name or None))
        except Exception as e:  # noqa: BLE001 — один битый файл не должен блокировать согласие
            logger.error(f"Согласие ПД: не удалось отправить документ {name or url}: {e}")
    await message.answer(view["text"], reply_markup=kb.pd_consent_kb())
    logger.info(f"🤖 Бот → @{username or '—'}: экран согласия на обработку ПД (152-ФЗ)")


async def _show_start(message: Message, pool: asyncpg.Pool, tg_id: int) -> None:
    """Показывает стартовый экран новым сообщением (общая часть /start и /menu)."""
    await repo.set_fsm_state(pool, tg_id, "screen:start")
    subscribed = await repo.get_active_subscription(pool, tg_id) is not None
    view = await screens.resolve(pool, "start")
    await screens.render(
        message, text=view["text"], markup=await menu.welcome_kb(pool, subscribed),
        photo_url=view["photo_url"], edit=False,
    )


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
        rule = await repo.get_referral_rule(pool, ref_rules.CATEGORY_BANYA)
        await message.answer(texts.referral_bound(ref_rules.discount_phrase(rule)))
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
    # Реферальный deep-link: `/start ref_<code>` — привязываем новичка (до гейта
    # согласия: код из ссылки нельзя терять, привязка не раскрывает ПД).
    code = ref.parse_start_payload(command.args)
    if code:
        await _try_bind_referral(pool, message, code)
    # Гейт 152-ФЗ: без согласия дальше стартового экрана не пускаем (этап 49).
    if await _needs_pd_consent(pool, u.id):
        await _show_consent(message, pool, u.id, u.username)
        return
    await _show_start(message, pool, u.id)
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
    # Отдельный экран «Главное меню» убран как дубль приветствия (этап 38):
    # /menu — синоним /start, показывает стартовый экран.
    await state.clear()
    u = message.from_user
    await repo.upsert_user(pool, u.id, u.username, u.first_name)
    if await _needs_pd_consent(pool, u.id):
        await _show_consent(message, pool, u.id, u.username)
        return
    await _show_start(message, pool, u.id)
    logger.info(f"🤖 Бот → @{u.username or '—'}: главное меню /menu (стартовый экран)")


@router.callback_query(F.data == kb.PD_AGREE)
async def cb_pd_agree(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    """Нажал «Согласен» на экране согласия ПД (этап 49): фиксируем факт → стартовый экран."""
    await state.clear()
    u = cb.from_user
    await repo.set_pd_consent(pool, u.id, consent.PD_CONSENT_VERSION)
    await repo.set_fsm_state(pool, u.id, "screen:start")
    subscribed = await repo.get_active_subscription(pool, u.id) is not None
    view = await screens.resolve(pool, "start")
    await screens.render(
        cb.message, text=view["text"], markup=await menu.welcome_kb(pool, subscribed),
        photo_url=view["photo_url"], edit=True,
    )
    await cb.answer("Спасибо! Согласие сохранено.")
    logger.info(
        f"🤖 Бот → @{u.username or '—'} (id:{u.id}): согласие на обработку ПД сохранено "
        f"(v{consent.PD_CONSENT_VERSION})"
    )
