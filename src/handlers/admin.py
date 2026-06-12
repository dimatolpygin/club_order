"""Админ-панель — пошаговый FSM-сценарий с инлайн-меню (этап 2).

Навигация кнопками, ввод значений по шагам («введите цену», «введите лимит»).
Доступ — только для id из ADMIN_IDS. Полный набор функций — этап 8.
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import repo
from ..config import settings
from ..logger import logger
from ..services import tariffs
from ..states import AdminStates
from ..utils import add_months, fmt_price

router = Router()


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.admin_id_list


# ── Клавиатуры панели ────────────────────────────────────────────────────────
def _main_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Ценовые ступени", callback_data="adm:tiers"))
    b.row(InlineKeyboardButton(text="Длительности", callback_data="adm:durs"))
    b.row(InlineKeyboardButton(text="Добавить участника", callback_data="adm:maddstart"))
    b.row(InlineKeyboardButton(text="Статистика", callback_data="adm:stats"))
    b.row(InlineKeyboardButton(text="Закрыть", callback_data="adm:close"))
    return b


def _cancel_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    return b


_MAIN_TEXT = "<b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери раздел:"


async def _show(cb: CallbackQuery, text: str, b: InlineKeyboardBuilder) -> None:
    with suppress(TelegramBadRequest):
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()


# ── Вход ─────────────────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(_MAIN_TEXT, reply_markup=_main_kb().as_markup())
    logger.info(f"⚙️ Админ @{message.from_user.username or '—'} открыл панель")


@router.callback_query(F.data == "adm:menu")
async def adm_menu(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.clear()
    await _show(cb, _MAIN_TEXT, _main_kb())


@router.callback_query(F.data == "adm:close")
async def adm_close(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    with suppress(TelegramBadRequest):
        await cb.message.edit_text("Панель закрыта. /admin — открыть снова.")
    await cb.answer()


# ── Ступени ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:tiers")
async def adm_tiers(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tiers = await repo.get_all_tiers(pool)
    occ = await repo.tier_occupancy(pool)
    lines = [
        "<b>ЦЕНОВЫЕ СТУПЕНИ</b>",
        "<i>Брекеты по местам. Текущая ставка выбирается автоматически по числу занятых мест.</i>",
        "",
    ]
    b = InlineKeyboardBuilder()
    for t in tiers:
        limit = "∞" if t["seat_limit"] is None else str(t["seat_limit"])
        status = "вкл" if t["is_active"] else "выкл"
        lines.append(
            f"#{t['id']} {escape(t['name'])} — {fmt_price(t['monthly_price'])} ₽/мес · "
            f"мест-брекет {limit} · занято {occ.get(t['id'], 0)} · {status}"
        )
        b.row(InlineKeyboardButton(text=f"✎ #{t['id']} {t['name']}", callback_data=f"adm:tier:{t['id']}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)


async def _tier_menu(cb: CallbackQuery, pool: asyncpg.Pool, tier_id: int) -> None:
    t = await repo.get_tier(pool, tier_id)
    if t is None:
        return await _show(cb, "Ступень не найдена.", _main_kb())
    limit = "безлимит" if t["seat_limit"] is None else str(t["seat_limit"])
    text = (
        f"<b>Ступень #{t['id']} — {escape(t['name'])}</b>\n\n"
        f"Цена: {fmt_price(t['monthly_price'])} ₽ / месяц\n"
        f"Лимит мест (брекет): {limit}\n"
        f"Активна: {'да' if t['is_active'] else 'нет'}\n\n"
        "Что меняем?"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Цена", callback_data=f"adm:tprice:{tier_id}"))
    b.row(InlineKeyboardButton(text="Лимит мест", callback_data=f"adm:tlimit:{tier_id}"))
    b.row(InlineKeyboardButton(text="Название", callback_data=f"adm:tname:{tier_id}"))
    b.row(InlineKeyboardButton(
        text="Выключить" if t["is_active"] else "Включить",
        callback_data=f"adm:ttoggle:{tier_id}",
    ))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:tiers"))
    await _show(cb, text, b)


@router.callback_query(F.data.startswith("adm:tier:"))
async def adm_tier(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await _tier_menu(cb, pool, int(cb.data.rsplit(":", 1)[1]))


@router.callback_query(F.data.startswith("adm:ttoggle:"))
async def adm_tier_toggle(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tier_id = int(cb.data.rsplit(":", 1)[1])
    t = await repo.get_tier(pool, tier_id)
    if t is not None:
        await repo.update_tier(pool, tier_id, is_active=not t["is_active"])
        await tariffs.invalidate(redis)
        logger.info(f"⚙️ Админ: ступень #{tier_id} active={not t['is_active']}")
    await _tier_menu(cb, pool, tier_id)


@router.callback_query(F.data.startswith("adm:tprice:"))
async def adm_tier_price_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tier_id = int(cb.data.rsplit(":", 1)[1])
    await state.set_state(AdminStates.tier_price)
    await state.update_data(tier_id=tier_id)
    await _show(cb, "Введите новую цену в рублях за месяц (например 900):", _cancel_kb())


@router.callback_query(F.data.startswith("adm:tlimit:"))
async def adm_tier_limit_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tier_id = int(cb.data.rsplit(":", 1)[1])
    await state.set_state(AdminStates.tier_limit)
    await state.update_data(tier_id=tier_id)
    await _show(cb, "Введите лимит мест для ступени (число; 0 — безлимит):", _cancel_kb())


@router.callback_query(F.data.startswith("adm:tname:"))
async def adm_tier_name_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tier_id = int(cb.data.rsplit(":", 1)[1])
    await state.set_state(AdminStates.tier_name)
    await state.update_data(tier_id=tier_id)
    await _show(cb, "Введите новое название ступени:", _cancel_kb())


@router.message(AdminStates.tier_price)
async def adm_tier_price_set(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        price = Decimal((message.text or "").replace(",", ".").strip())
        if price <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return await message.answer("Не похоже на цену. Введите число, например 900:")
    tier_id = (await state.get_data())["tier_id"]
    await repo.update_tier(pool, tier_id, monthly_price=price)
    await tariffs.invalidate(redis)
    await state.clear()
    await message.answer(
        f"Цена ступени #{tier_id} обновлена: {fmt_price(price)} ₽/мес.",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"⚙️ Админ: цена ступени #{tier_id} = {price}")


@router.message(AdminStates.tier_limit)
async def adm_tier_limit_set(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введите целое число (0 — безлимит):")
    n = int(raw)
    limit = None if n == 0 else n
    tier_id = (await state.get_data())["tier_id"]
    await repo.update_tier(pool, tier_id, seat_limit=limit)
    await tariffs.invalidate(redis)
    await state.clear()
    await message.answer(
        f"Лимит мест ступени #{tier_id}: {'безлимит' if limit is None else limit}.",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"⚙️ Админ: лимит ступени #{tier_id} = {limit}")


@router.message(AdminStates.tier_name)
async def adm_tier_name_set(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        return await message.answer("Название пустое. Введите ещё раз:")
    tier_id = (await state.get_data())["tier_id"]
    await repo.update_tier(pool, tier_id, name=name)
    await tariffs.invalidate(redis)
    await state.clear()
    await message.answer(
        f"Название ступени #{tier_id}: «{escape(name)}».",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"⚙️ Админ: название ступени #{tier_id} = {name}")


# ── Длительности ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:durs")
async def adm_durs(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await repo.get_all_durations(pool)
    lines = ["<b>ДЛИТЕЛЬНОСТИ</b>", "Нажми, чтобы включить/выключить:", ""]
    b = InlineKeyboardBuilder()
    for r in rows:
        mark = "✓" if r["is_active"] else "✕"
        lines.append(f"{mark} {r['months']} мес")
        b.row(InlineKeyboardButton(
            text=f"{mark} {r['months']} мес",
            callback_data=f"adm:dtoggle:{r['months']}",
        ))
    b.row(InlineKeyboardButton(text="Добавить длительность", callback_data="adm:dadd"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)


@router.callback_query(F.data.startswith("adm:dtoggle:"))
async def adm_dur_toggle(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    months = int(cb.data.rsplit(":", 1)[1])
    rows = {r["months"]: r for r in await repo.get_all_durations(pool)}
    cur = rows.get(months)
    if cur is not None:
        await repo.set_duration_active(pool, months, not cur["is_active"])
        await tariffs.invalidate(redis)
        logger.info(f"⚙️ Админ: длительность {months} мес active={not cur['is_active']}")
    await adm_durs(cb, pool)


@router.callback_query(F.data == "adm:dadd")
async def adm_dur_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.dur_add)
    await _show(cb, "Введите число месяцев для новой длительности (например 9):", _cancel_kb())


@router.message(AdminStates.dur_add)
async def adm_dur_add_set(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return await message.answer("Введите положительное целое число месяцев:")
    months = int(raw)
    await repo.upsert_duration(pool, months, True)
    await tariffs.invalidate(redis)
    await state.clear()
    await message.answer(
        f"Длительность {months} мес добавлена и включена.",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"⚙️ Админ: добавлена длительность {months} мес")


# ── Добавление участника вручную ─────────────────────────────────────────────
@router.callback_query(F.data == "adm:maddstart")
async def adm_member_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.member_id)
    await _show(
        cb,
        "Добавление участника вручную.\n\nВведите Telegram ID пользователя (число):",
        _cancel_kb(),
    )


@router.message(AdminStates.member_id)
async def adm_member_id(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        return await message.answer("Введите числовой Telegram ID:")
    await state.update_data(member_tg_id=int(raw))
    await state.set_state(AdminStates.member_months)
    await message.answer("На сколько месяцев выдать подписку? (число):", reply_markup=_cancel_kb().as_markup())


@router.message(AdminStates.member_months)
async def adm_member_months(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return await message.answer("Введите положительное число месяцев:")
    months = int(raw)
    tg_id = (await state.get_data())["member_tg_id"]

    # Цена — текущая ставка движка на момент добавления.
    tier = await tariffs.get_current_tier(pool, redis)
    if tier is None:
        await state.clear()
        return await message.answer(
            "Не удалось определить текущую ставку (нет активных ступеней).",
            reply_markup=_main_kb().as_markup(),
        )
    await repo.upsert_user(pool, tg_id, None, None)
    end_date = add_months(datetime.now(timezone.utc), months)
    sub_id = await repo.add_subscription(
        pool, tg_id, tier["id"], tier["monthly_price"], months, end_date,
        source="manual", status="active",
    )
    await state.clear()
    await message.answer(
        f"Подписка #{sub_id} создана: tg_id <code>{tg_id}</code>, "
        f"{fmt_price(tier['monthly_price'])} ₽/мес × {months} мес, до {end_date:%d.%m.%Y}.",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"⚙️ Админ вручную добавил подписку #{sub_id} для tg_id={tg_id}")


# ── Статистика ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    taken = await repo.count_active_members(pool)
    tier = await tariffs.get_current_tier(pool, redis)
    cur = (
        f"{escape(tier['name'])} — {fmt_price(tier['monthly_price'])} ₽/мес"
        if tier else "—"
    )
    text = (
        "<b>СТАТИСТИКА</b>\n\n"
        f"Активных участников (занято мест): <b>{taken}</b>\n"
        f"Текущая ставка: {cur}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, text, b)
