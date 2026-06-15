"""Админ-панель — пошаговый FSM-сценарий с инлайн-меню (этап 2).

Навигация кнопками, ввод значений по шагам («введите цену», «введите лимит»).
Доступ — только для id из ADMIN_IDS. Полный набор функций — этап 8.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InputMediaPhoto, Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..services import (
    app_settings, promo as promo_service, storage, subscriptions, tariffs,
)
from ..states import AdminStates
from ..utils import add_period, fmt_price

router = Router()


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.admin_id_list


# ── Клавиатуры панели ────────────────────────────────────────────────────────
def _main_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Ценовые ступени", callback_data="adm:tiers"))
    b.row(InlineKeyboardButton(text="Длительности", callback_data="adm:durs"))
    b.row(
        InlineKeyboardButton(text="Поиск участника", callback_data="adm:findstart"),
        InlineKeyboardButton(text="Добавить участника", callback_data="adm:maddstart"),
    )
    b.row(InlineKeyboardButton(text="Рассылка", callback_data="adm:bcaststart"))
    b.row(InlineKeyboardButton(text="Промокоды", callback_data="adm:promos"))
    b.row(
        InlineKeyboardButton(text="Напоминания", callback_data="adm:rem"),
        InlineKeyboardButton(text="Застрявшие в FSM", callback_data="adm:fsm"),
    )
    b.row(InlineKeyboardButton(text="Ссылка поддержки", callback_data="adm:support"))
    b.row(InlineKeyboardButton(text="Статистика", callback_data="adm:stats"))
    b.row(InlineKeyboardButton(text="Закрыть", callback_data="adm:close"))
    return b


def _cancel_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    return b


# Поддерживаемые единицы длительности (порядок — для кнопок выбора).
_UNITS = ("month", "day", "hour", "minute")


def _unit_kb(action: str) -> InlineKeyboardBuilder:
    """Клавиатура выбора единицы: callback вида f'{action}:{unit}'."""
    b = InlineKeyboardBuilder()
    for u in _UNITS:
        b.button(text=texts.UNIT_LABELS[u], callback_data=f"{action}:{u}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    return b


_MAIN_TEXT = (
    "<b>АДМИН-ПАНЕЛЬ</b>\n\n"
    "Доступные команды:\n"
    "· <b>Ценовые ступени</b> — цены, лимиты мест, цены за периоды\n"
    "· <b>Длительности</b> — добавить/включить/удалить сроки подписки\n"
    "· <b>Поиск участника</b> — статус подписки и доступа по Telegram ID\n"
    "· <b>Добавить участника</b> — выдать подписку оплатившему вручную\n"
    "· <b>Рассылка</b> — сообщение всем пользователям базы\n"
    "· <b>Промокоды</b> — создать/включить/выключить коды\n"
    "· <b>Напоминания</b> — пороги и единица напоминаний о продлении\n"
    "· <b>Застрявшие в FSM</b> — кто на каком шаге сценария\n"
    "· <b>Ссылка поддержки</b> — куда ведёт кнопка «Перейти» в разделе «Поддержка»\n"
    "· <b>Статистика</b> — занятые места и текущая ставка\n\n"
    "Выбери раздел:"
)


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
    b.row(InlineKeyboardButton(text="Цена за 1 мес (ставка)", callback_data=f"adm:tprice:{tier_id}"))
    b.row(InlineKeyboardButton(text="Цены за периоды (3/6/12…)", callback_data=f"adm:tperiods:{tier_id}"))
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


# ── Цены за периоды внутри ступени (матрица ступень×период) ───────────────────
async def _periods_menu(cb: CallbackQuery, pool: asyncpg.Pool, tier_id: int) -> None:
    t = await repo.get_tier(pool, tier_id)
    if t is None:
        return await _show(cb, "Ступень не найдена.", _main_kb())
    monthly = t["monthly_price"]
    durations = await repo.get_active_durations(pool)
    overrides = await repo.get_tier_prices(pool, tier_id)
    lines = [
        f"<b>ЦЕНЫ ЗА ПЕРИОДЫ — ступень #{tier_id} «{escape(t['name'])}»</b>",
        f"Ставка за 1 мес: {fmt_price(monthly)} ₽",
        "<i>Период без своей цены считается как ставка×значение. Можно задать любую цену.</i>",
        "",
    ]
    b = InlineKeyboardBuilder()
    # Цену можно задать для любой активной длительности, кроме канонического «1 месяц»
    # (он равен ставке). Для дней/часов/минут цену обычно задаёт админ.
    settable = [d for d in durations if not (d["months"] == 1 and d["unit"] == "month")]
    if not settable:
        lines.append("Нет активных периодов для своей цены.")
    for d in settable:
        key = (d["months"], d["unit"])
        custom = key in overrides
        price = overrides[key] if custom else monthly * d["months"]
        label = texts.period_phrase(d["months"], d["unit"])
        lines.append(f"{label} — {fmt_price(price)} ₽ ({'своя' if custom else 'авто'})")
        b.row(InlineKeyboardButton(
            text=f"✎ {label} — {fmt_price(price)} ₽",
            callback_data=f"adm:tpset:{tier_id}:{d['id']}",
        ))
        if custom:
            b.row(InlineKeyboardButton(
                text=f"↺ Сброс {label} (к авто)",
                callback_data=f"adm:tpreset:{tier_id}:{d['id']}",
            ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=f"adm:tier:{tier_id}"))
    await _show(cb, "\n".join(lines), b)


@router.callback_query(F.data.startswith("adm:tperiods:"))
async def adm_tier_periods(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await _periods_menu(cb, pool, int(cb.data.rsplit(":", 1)[1]))


@router.callback_query(F.data.startswith("adm:tpset:"))
async def adm_tier_period_set_start(
    cb: CallbackQuery, state: FSMContext, pool: asyncpg.Pool
) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    _, _, tier_id, dur_id = cb.data.split(":")
    duration = await repo.get_duration(pool, int(dur_id))
    if duration is None:
        return await _periods_menu(cb, pool, int(tier_id))
    value, unit = duration["months"], duration["unit"]
    await state.set_state(AdminStates.tier_period_price)
    await state.update_data(tier_id=int(tier_id), value=value, unit=unit)
    await _show(
        cb,
        f"Введите цену за {texts.period_phrase(value, unit)} в рублях (например 3000). "
        "Это итоговая сумма за весь период:",
        _cancel_kb(),
    )


@router.callback_query(F.data.startswith("adm:tpreset:"))
async def adm_tier_period_reset(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    _, _, tier_id, dur_id = cb.data.split(":")
    duration = await repo.get_duration(pool, int(dur_id))
    if duration is not None:
        await repo.delete_tier_price(pool, int(tier_id), duration["months"], duration["unit"])
        await tariffs.invalidate(redis)
        logger.info(
            f"⚙️ Админ: сброс цены {duration['months']}{duration['unit']} "
            f"ступени #{tier_id} (к авто)"
        )
    await _periods_menu(cb, pool, int(tier_id))


@router.message(AdminStates.tier_period_price)
async def adm_tier_period_set(
    message: Message, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        price = Decimal((message.text or "").replace(",", ".").strip())
        if price <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return await message.answer("Не похоже на цену. Введите число, например 3000:")
    data = await state.get_data()
    tier_id, value, unit = data["tier_id"], data["value"], data["unit"]
    await repo.set_tier_price(pool, tier_id, value, unit, price)
    await tariffs.invalidate(redis)
    await state.clear()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="К периодам", callback_data=f"adm:tperiods:{tier_id}"))
    b.row(InlineKeyboardButton(text="В меню", callback_data="adm:menu"))
    await message.answer(
        f"Цена за {texts.period_phrase(value, unit)} ступени #{tier_id}: {fmt_price(price)} ₽.",
        reply_markup=b.as_markup(),
    )
    logger.info(f"⚙️ Админ: цена {value}{unit} ступени #{tier_id} = {price}")


# ── Длительности ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:durs")
async def adm_durs(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await repo.get_all_durations(pool)
    lines = [
        "<b>ДЛИТЕЛЬНОСТИ</b>",
        "Слева — вкл/выкл, справа — удалить период.",
        "",
    ]
    b = InlineKeyboardBuilder()
    for r in rows:
        mark = "✓" if r["is_active"] else "✕"
        label = texts.period_phrase(r["months"], r["unit"])
        lines.append(f"{mark} {label}")
        b.row(
            InlineKeyboardButton(
                text=f"{mark} {label}", callback_data=f"adm:dtoggle:{r['id']}"
            ),
            InlineKeyboardButton(text="Удалить", callback_data=f"adm:ddel:{r['id']}"),
        )
    b.row(InlineKeyboardButton(text="Добавить длительность", callback_data="adm:dadd"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)


@router.callback_query(F.data.startswith("adm:dtoggle:"))
async def adm_dur_toggle(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    dur_id = int(cb.data.rsplit(":", 1)[1])
    cur = await repo.get_duration(pool, dur_id)
    if cur is not None:
        await repo.set_duration_active(pool, dur_id, not cur["is_active"])
        await tariffs.invalidate(redis)
        logger.info(
            f"⚙️ Админ: длительность #{dur_id} "
            f"{cur['months']}{cur['unit']} active={not cur['is_active']}"
        )
    await adm_durs(cb, pool)


@router.callback_query(F.data.startswith("adm:ddel:"))
async def adm_dur_del_confirm(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    dur_id = int(cb.data.rsplit(":", 1)[1])
    d = await repo.get_duration(pool, dur_id)
    if d is None:
        return await adm_durs(cb, pool)
    label = texts.period_phrase(d["months"], d["unit"])
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Да, удалить", callback_data=f"adm:ddelyes:{dur_id}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:durs"))
    await _show(
        cb,
        f"Удалить длительность «{label}»?\n\n"
        "Она исчезнет из списка и из выбора у пользователей. Заданные для неё цены "
        "будут сброшены. Уже оформленные подписки не затрагиваются.",
        b,
    )


@router.callback_query(F.data.startswith("adm:ddelyes:"))
async def adm_dur_del_do(cb: CallbackQuery, pool: asyncpg.Pool, redis: Redis) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    dur_id = int(cb.data.rsplit(":", 1)[1])
    deleted = await repo.delete_duration(pool, dur_id)
    if deleted:
        await tariffs.invalidate(redis)
        logger.info(f"⚙️ Админ удалил длительность #{dur_id}")
    await adm_durs(cb, pool)


@router.callback_query(F.data == "adm:dadd")
async def adm_dur_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.dur_add_value)
    await _show(cb, "Введите число для новой длительности (например 1, 3, 7):", _cancel_kb())


@router.message(AdminStates.dur_add_value)
async def adm_dur_add_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return await message.answer("Введите положительное целое число:")
    await state.update_data(dur_value=int(raw))
    await state.set_state(AdminStates.dur_add_unit)
    await message.answer(
        f"Длительность: {raw}. Выберите единицу:",
        reply_markup=_unit_kb("adm:dunit").as_markup(),
    )


@router.callback_query(AdminStates.dur_add_unit, F.data.startswith("adm:dunit:"))
async def adm_dur_add_unit(
    cb: CallbackQuery, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    unit = cb.data.rsplit(":", 1)[1]
    value = (await state.get_data())["dur_value"]
    await repo.upsert_duration(pool, value, unit, True)
    await tariffs.invalidate(redis)
    await state.clear()
    await _show(
        cb,
        f"Длительность {texts.period_phrase(value, unit)} добавлена и включена.",
        _main_kb(),
    )
    logger.info(f"⚙️ Админ: добавлена длительность {value} {unit}")


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
    await state.set_state(AdminStates.member_value)
    await message.answer(
        "На какой срок выдать подписку? Введите число (единицу выберете далее):",
        reply_markup=_cancel_kb().as_markup(),
    )


@router.message(AdminStates.member_value)
async def adm_member_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return await message.answer("Введите положительное целое число:")
    await state.update_data(member_value=int(raw))
    await state.set_state(AdminStates.member_unit)
    await message.answer(
        f"Срок: {raw}. Выберите единицу:",
        reply_markup=_unit_kb("adm:munit").as_markup(),
    )


@router.callback_query(AdminStates.member_unit, F.data.startswith("adm:munit:"))
async def adm_member_unit(
    cb: CallbackQuery, state: FSMContext, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    unit = cb.data.rsplit(":", 1)[1]
    data = await state.get_data()
    tg_id, value = data["member_tg_id"], data["member_value"]

    # Цена — текущая ставка движка на момент добавления.
    tier = await tariffs.get_current_tier(pool, redis)
    if tier is None:
        await state.clear()
        return await _show(
            cb, "Не удалось определить текущую ставку (нет активных ступеней).", _main_kb()
        )
    await repo.upsert_user(pool, tg_id, None, None)
    end_date = add_period(datetime.now(timezone.utc), value, unit)
    sub_id = await repo.add_subscription(
        pool, tg_id, tier["id"], tier["monthly_price"], value, end_date,
        source="manual", status="active", unit=unit,
    )
    await state.clear()
    await _show(
        cb,
        f"Подписка #{sub_id} создана: tg_id <code>{tg_id}</code>, "
        f"{fmt_price(tier['monthly_price'])} ₽/мес · {texts.period_phrase(value, unit)}, "
        f"до {end_date:%d.%m.%Y %H:%M}.",
        _main_kb(),
    )
    logger.info(f"⚙️ Админ вручную добавил подписку #{sub_id} для tg_id={tg_id} ({value} {unit})")


# ── Поиск участника / карточка статуса ───────────────────────────────────────
def _sub_line(sub) -> str:
    now = datetime.now(timezone.utc)
    remaining = texts.remaining_phrase(sub["end_date"], now, sub["unit"])
    src = {"payment": "оплата", "manual": "вручную", "promo": "промокод"}.get(
        sub["source"], sub["source"]
    )
    return (
        f"{fmt_price(sub['fixed_price'])} ₽/мес · {texts.period_phrase(sub['months'], sub['unit'])} · "
        f"{sub['start_date']:%d.%m.%Y %H:%M}–{sub['end_date']:%d.%m.%Y %H:%M} "
        f"(осталось {remaining}) · статус {sub['status']} · источник {src}"
    )


async def _user_card(pool: asyncpg.Pool, tg_id: int) -> tuple[str, bool]:
    """Возвращает (текст карточки, есть ли активная подписка)."""
    user = await repo.get_user(pool, tg_id)
    active = await repo.get_active_subscription(pool, tg_id)
    last = await repo.get_last_subscription(pool, tg_id)

    if user is None and last is None:
        return f"Пользователь <code>{tg_id}</code> не найден в базе.", False

    lines = [f"<b>УЧАСТНИК</b> <code>{tg_id}</code>", ""]
    if user is not None:
        lines.append(f"Username: @{escape(user['username'] or '—')}")
        lines.append(f"Имя: {escape(user['first_name'] or '—')}")
        if user["email"]:
            lines.append(f"Email: {escape(user['email'])}")
        if user["is_blocked"]:
            lines.append("⚠️ Заблокирован")
    lines.append("")

    if active is not None:
        lines.append("Подписка: <b>активна</b>")
        lines.append("  " + _sub_line(active))
        lines.append("Доступ в клуб: <b>да</b> (по активной подписке)")
    else:
        lines.append("Подписка: <b>нет активной</b>")
        if last is not None:
            lines.append("Последняя: " + _sub_line(last))
        lines.append("Доступ в клуб: <b>нет</b>")

    return "\n".join(lines), active is not None


def _card_kb(tg_id: int, has_active: bool) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if has_active:
        b.row(InlineKeyboardButton(
            text="Аннулировать подписку", callback_data=f"adm:cancelsub:{tg_id}"
        ))
    b.row(InlineKeyboardButton(text="В меню", callback_data="adm:menu"))
    return b


@router.callback_query(F.data == "adm:findstart")
async def adm_find_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.user_lookup)
    await _show(cb, "Введите Telegram ID участника для проверки статуса:", _cancel_kb())


@router.message(AdminStates.user_lookup)
async def adm_find_result(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        return await message.answer("Введите числовой Telegram ID:")
    await state.clear()
    tg_id = int(raw)
    card, has_active = await _user_card(pool, tg_id)
    await message.answer(card, reply_markup=_card_kb(tg_id, has_active).as_markup())
    logger.info(f"⚙️ Админ смотрел карточку tg_id={tg_id}")


@router.callback_query(F.data.startswith("adm:card:"))
async def adm_card_refresh(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tg_id = int(cb.data.rsplit(":", 1)[1])
    card, has_active = await _user_card(pool, tg_id)
    await _show(cb, card, _card_kb(tg_id, has_active))


@router.callback_query(F.data.startswith("adm:cancelsub:"))
async def adm_cancel_confirm(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tg_id = int(cb.data.rsplit(":", 1)[1])
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Да, аннулировать", callback_data=f"adm:cancelyes:{tg_id}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data=f"adm:card:{tg_id}"))
    await _show(
        cb,
        f"Аннулировать активную подписку участника <code>{tg_id}</code>?\n\n"
        "Место освободится, и участник будет сразу удалён из закрытой группы.",
        b,
    )


@router.callback_query(F.data.startswith("adm:cancelyes:"))
async def adm_cancel_do(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    tg_id = int(cb.data.rsplit(":", 1)[1])
    n = await repo.cancel_active_subscriptions(pool, tg_id)
    # Аннулирование освобождает место — сразу удаляем участника из закрытой группы.
    if n > 0:
        await subscriptions.kick_from_group(bot, tg_id, reason="подписка аннулирована админом")
    await cb.answer(f"Аннулировано подписок: {n}", show_alert=True)
    logger.info(f"⚙️ Админ аннулировал {n} подписк(и) участника tg_id={tg_id}")
    card, has_active = await _user_card(pool, tg_id)
    await _show(cb, card, _card_kb(tg_id, has_active))


# ── Рассылка по базе (текст и/или фото-альбом) ───────────────────────────────
_BCAST_MAX_PHOTOS = 10  # лимит Telegram на media_group


def _bcast_compose_kb(count: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    if count > 0:
        b.row(InlineKeyboardButton(text="Готово — к предпросмотру", callback_data="adm:bcast_ready"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    return b


@router.callback_query(F.data == "adm:bcaststart")
async def adm_bcast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.broadcast_compose)
    await state.update_data(bcast_text=None, bcast_photos=[])
    photo_note = (
        "Можно приложить фото (по одному или альбомом, до 10) и/или текст."
        if settings.s3_enabled
        else "Фото недоступны (S3 не настроен) — доступна только текстовая рассылка."
    )
    await _show(
        cb,
        "<b>Рассылка по базе</b>\n\n"
        f"{photo_note}\n\n"
        "Отправляйте сообщения, затем нажмите «Готово». HTML-разметка в тексте "
        "и подписи поддерживается.",
        _cancel_kb(),
    )


# Сбор альбомов: media_group приходит несколькими сообщениями ОДНОВРЕМЕННО, поэтому
# копим их по media_group_id и обрабатываем одной пачкой после короткой паузы —
# иначе параллельные хендлеры перезатирают список фото в FSM.
_album_buffer: dict[str, list[Message]] = {}
_ALBUM_DEBOUNCE = 1.5  # сек ожидания остальных фото альбома


async def _process_bcast_photos(
    messages: list[Message], state: FSMContext, bot: Bot
) -> None:
    """Загружает пачку фото в S3 и обновляет FSM-данные рассылки ОДИН раз."""
    data = await state.get_data()
    photos = list(data.get("bcast_photos") or [])
    text = data.get("bcast_text")
    # Загрузка (особенно альбома) занимает время — сразу показываем статус.
    status = await messages[0].answer(
        f"Загружаю фото в хранилище ({len(messages)} шт.), подождите…"
    )
    added = failed = skipped = 0
    for m in messages:
        if len(photos) >= _BCAST_MAX_PHOTOS:
            skipped += 1
            continue
        try:
            buf = await bot.download(m.photo[-1])
            url = await storage.upload_photo(buf.read(), "jpg")
            photos.append({"url": url, "file_id": m.photo[-1].file_id})
            added += 1
        except Exception as e:  # noqa: BLE001 — ошибка фото не должна ронять сценарий
            failed += 1
            logger.error(f"Рассылка: не удалось загрузить фото в S3: {e}")
        caption = m.html_text or m.caption
        if caption and not text:
            text = caption
    await state.update_data(bcast_photos=photos, bcast_text=text)
    note = f"Фото добавлено: {added} (всего: {len(photos)})."
    if failed:
        note += f" Не загрузилось: {failed}."
    if skipped:
        note += f" Превышен лимит {_BCAST_MAX_PHOTOS}, лишние пропущены."
    with suppress(TelegramBadRequest):
        await status.edit_text(note, reply_markup=_bcast_compose_kb(len(photos)).as_markup())


async def _finalize_album(key: str, state: FSMContext, bot: Bot) -> None:
    await asyncio.sleep(_ALBUM_DEBOUNCE)
    messages = _album_buffer.pop(key, [])
    if messages:
        await _process_bcast_photos(messages, state, bot)


@router.message(AdminStates.broadcast_compose, F.photo)
async def adm_bcast_add_photo(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    if not _is_admin(message.from_user.id):
        return
    if not settings.s3_enabled:
        return await message.answer("Фото недоступны: S3 не настроен. Пришлите текст.")
    # Одиночное фото — сразу; альбом — копим по группе и обрабатываем пачкой.
    if message.media_group_id is None:
        await _process_bcast_photos([message], state, bot)
        return
    key = f"{message.chat.id}:{message.media_group_id}"
    is_first = key not in _album_buffer
    _album_buffer.setdefault(key, []).append(message)
    if is_first:
        asyncio.create_task(_finalize_album(key, state, bot))


@router.message(AdminStates.broadcast_compose, F.text)
async def adm_bcast_add_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if not text.strip():
        return await message.answer("Пустое сообщение. Пришлите текст или фото.")
    await state.update_data(bcast_text=text)
    count = len((await state.get_data()).get("bcast_photos") or [])
    await message.answer(
        "Текст сохранён.",
        reply_markup=_bcast_compose_kb(max(count, 1)).as_markup(),
    )


@router.callback_query(F.data == "adm:bcast_ready")
async def adm_bcast_ready(cb: CallbackQuery, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    data = await state.get_data()
    text = data.get("bcast_text")
    photos = data.get("bcast_photos") or []
    if not text and not photos:
        return await _show(cb, "Пока нечего отправлять — добавьте текст или фото.", _cancel_kb())
    count = len(await repo.get_all_user_ids(pool))
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"Отправить всем ({count})", callback_data="adm:bcast_go"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    preview = (
        "<b>Предпросмотр рассылки</b>\n\n"
        f"Фото: {len(photos)}\n"
        f"Текст: {text if text else '—'}\n\n"
        f"Получателей: {count}"
    )
    await _show(cb, preview, b)


def _bcast_media(photos: list[dict], text: str | None, by_url: bool) -> list[InputMediaPhoto]:
    """Собирает media_group; подпись — только на первом фото."""
    key = "url" if by_url else "file_id"
    return [
        InputMediaPhoto(media=p[key], caption=text if (i == 0 and text) else None)
        for i, p in enumerate(photos)
    ]


async def _bcast_send_one(bot: Bot, uid: int, text: str | None, photos: list[dict]) -> None:
    """Отправляет один экземпляр рассылки. URL из S3, при сбое — fallback на file_id."""
    if not photos:
        await bot.send_message(uid, text)
    elif len(photos) == 1:
        try:
            await bot.send_photo(uid, photos[0]["url"], caption=text)
        except TelegramBadRequest:
            await bot.send_photo(uid, photos[0]["file_id"], caption=text)
    else:
        try:
            await bot.send_media_group(uid, _bcast_media(photos, text, by_url=True))
        except TelegramBadRequest:
            await bot.send_media_group(uid, _bcast_media(photos, text, by_url=False))


@router.callback_query(F.data == "adm:bcast_go")
async def adm_bcast_go(
    cb: CallbackQuery, state: FSMContext, bot: Bot, pool: asyncpg.Pool
) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    data = await state.get_data()
    text = data.get("bcast_text")
    photos = data.get("bcast_photos") or []
    await state.clear()
    if not text and not photos:
        return await _show(cb, "Рассылка потеряна, начните заново.", _main_kb())

    await cb.answer("Рассылка запущена")
    with suppress(TelegramBadRequest):
        await cb.message.edit_text("Рассылка запущена, отправляю...")

    user_ids = await repo.get_all_user_ids(pool)
    sent = blocked = failed = 0
    for uid in user_ids:
        try:
            await _bcast_send_one(bot, uid, text, photos)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            await repo.set_user_blocked(pool, uid, True)
        except TelegramBadRequest:
            failed += 1
        # Альбом = несколько сообщений, шлём чуть медленнее, чтобы не упереться в лимиты.
        await asyncio.sleep(0.1 if photos else 0.05)
    await cb.message.answer(
        f"<b>Рассылка завершена</b>\n\nОтправлено: {sent}\n"
        f"Заблокировали бота: {blocked}\nОшибки: {failed}",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(
        f"📣 Рассылка ({len(photos)} фото): отправлено {sent}, заблок. {blocked}, "
        f"ошибок {failed}"
    )


# ── Промокоды ────────────────────────────────────────────────────────────────
def _promo_desc(p) -> str:
    """Краткое описание условий промокода для списка."""
    if p["kind"] == promo_service.KIND_PERCENT:
        cond = f"скидка {fmt_price(p['value'])}%"
    else:
        cond = f"спец {fmt_price(p['value'])} ₽/мес"
    limit = "∞" if p["max_activations"] is None else str(p["max_activations"])
    expiry = "бессрочно" if p["expires_at"] is None else f"{p['expires_at']:%d.%m.%Y}"
    fix = "фикс" if p["fixes_price"] else "разово"
    status = "вкл" if p["is_active"] else "выкл"
    return (
        f"{cond} · использовано {p['used_count']}/{limit} · до {expiry} · "
        f"{fix} · {status}"
    )


async def _promos_menu(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    promos = await repo.get_all_promos(pool)
    lines = ["<b>ПРОМОКОДЫ</b>", "Слева — вкл/выкл, справа — удалить.", ""]
    b = InlineKeyboardBuilder()
    if not promos:
        lines.append("<i>Пока нет ни одного промокода.</i>")
    for p in promos:
        lines.append(f"#{p['id']} <code>{escape(p['code'])}</code> — {_promo_desc(p)}")
        mark = "✓" if p["is_active"] else "✕"
        b.row(
            InlineKeyboardButton(
                text=f"{mark} {p['code']}", callback_data=f"adm:ptoggle:{p['id']}"
            ),
            InlineKeyboardButton(text="Удалить", callback_data=f"adm:pdel:{p['id']}"),
        )
    b.row(InlineKeyboardButton(text="Создать промокод", callback_data="adm:promonew"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)


@router.callback_query(F.data == "adm:promos")
async def adm_promos(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await _promos_menu(cb, pool)


@router.callback_query(F.data.startswith("adm:ptoggle:"))
async def adm_promo_toggle(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    promo_id = int(cb.data.rsplit(":", 1)[1])
    p = await repo.get_promo(pool, promo_id)
    if p is not None:
        await repo.set_promo_active(pool, promo_id, not p["is_active"])
        logger.info(f"⚙️ Админ: промокод #{promo_id} active={not p['is_active']}")
    await _promos_menu(cb, pool)


@router.callback_query(F.data.startswith("adm:pdel:"))
async def adm_promo_del_confirm(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    promo_id = int(cb.data.rsplit(":", 1)[1])
    p = await repo.get_promo(pool, promo_id)
    if p is None:
        return await _promos_menu(cb, pool)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Да, удалить", callback_data=f"adm:pdelyes:{promo_id}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:promos"))
    await _show(
        cb,
        f"Удалить промокод <code>{escape(p['code'])}</code>?\n\n"
        "Код исчезнет из списка, применить его больше будет нельзя. История его "
        "активаций удалится, в платежах ссылка на код обнулится (сами платежи "
        "сохранятся). Уже оформленные по нему подписки не затрагиваются.\n\n"
        "Если код нужно просто временно отключить — вернись и нажми вкл/выкл.",
        b,
    )


@router.callback_query(F.data.startswith("adm:pdelyes:"))
async def adm_promo_del_do(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    promo_id = int(cb.data.rsplit(":", 1)[1])
    deleted = await repo.delete_promo(pool, promo_id)
    if deleted:
        logger.info(f"⚙️ Админ удалил промокод #{promo_id}")
    await _promos_menu(cb, pool)


@router.callback_query(F.data == "adm:promonew")
async def adm_promo_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.promo_code)
    await _show(cb, "Введите промокод (буквы/цифры, например LAUNCH11):", _cancel_kb())


@router.message(AdminStates.promo_code)
async def adm_promo_code(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(message.from_user.id):
        return
    code = promo_service.normalize_code(message.text)
    if not code or " " in code or len(code) > 32:
        return await message.answer("Код пустой или некорректный. Введите ещё раз (без пробелов, до 32 символов):")
    if await repo.get_promo_by_code(pool, code) is not None:
        return await message.answer("Такой код уже существует. Введите другой:")
    await state.update_data(promo_code=code)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Спец-цена ₽/мес", callback_data="adm:pkind:fixed_price"))
    b.row(InlineKeyboardButton(text="Скидка %", callback_data="adm:pkind:percent"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    await message.answer(f"Код: <code>{escape(code)}</code>\n\nВыберите тип промокода:", reply_markup=b.as_markup())


@router.callback_query(AdminStates.promo_code, F.data.startswith("adm:pkind:"))
async def adm_promo_kind(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    kind = cb.data.rsplit(":", 1)[1]
    await state.update_data(promo_kind=kind)
    await state.set_state(AdminStates.promo_value)
    prompt = (
        "Введите процент скидки (1–99):"
        if kind == promo_service.KIND_PERCENT
        else "Введите спец-цену в рублях за месяц (например 555):"
    )
    await _show(cb, prompt, _cancel_kb())


@router.message(AdminStates.promo_value)
async def adm_promo_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    kind = data["promo_kind"]
    try:
        value = Decimal((message.text or "").replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return await message.answer("Не похоже на число. Введите ещё раз:")
    if kind == promo_service.KIND_PERCENT:
        if not (0 < value < 100):
            return await message.answer("Процент должен быть от 1 до 99. Введите ещё раз:")
    elif value <= 0:
        return await message.answer("Цена должна быть больше нуля. Введите ещё раз:")
    await state.update_data(promo_value=str(value))
    await state.set_state(AdminStates.promo_limit)
    await message.answer(
        "Лимит активаций (сколько раз можно применить; 0 — без лимита):",
        reply_markup=_cancel_kb().as_markup(),
    )


@router.message(AdminStates.promo_limit)
async def adm_promo_limit(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введите целое число (0 — без лимита):")
    await state.update_data(promo_limit=int(raw))
    await state.set_state(AdminStates.promo_expiry)
    await message.answer(
        "Срок действия в днях (0 — бессрочно):",
        reply_markup=_cancel_kb().as_markup(),
    )


@router.message(AdminStates.promo_expiry)
async def adm_promo_expiry(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введите целое число дней (0 — бессрочно):")
    await state.update_data(promo_expiry_days=int(raw))
    # Единицу «фиксации цены» спрашиваем кнопкой; состояние держим, чтобы не ловить
    # лишние сообщения, данные сохранены в FSM до создания.
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Фиксировать цену", callback_data="adm:pfix:1"),
        InlineKeyboardButton(text="Разовая скидка", callback_data="adm:pfix:0"),
    )
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    await message.answer(
        "Фиксировать ли спец-цену за пользователем для продлений?",
        reply_markup=b.as_markup(),
    )


@router.callback_query(AdminStates.promo_expiry, F.data.startswith("adm:pfix:"))
async def adm_promo_create(cb: CallbackQuery, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    fixes = cb.data.rsplit(":", 1)[1] == "1"
    data = await state.get_data()
    limit = data["promo_limit"]
    days = data["promo_expiry_days"]
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None
    )
    promo_id = await repo.create_promo(
        pool,
        code=data["promo_code"],
        kind=data["promo_kind"],
        value=Decimal(data["promo_value"]),
        max_activations=None if limit == 0 else limit,
        expires_at=expires_at,
        fixes_price=fixes,
    )
    await state.clear()
    if promo_id is None:
        return await _show(cb, "Не удалось создать: такой код уже существует.", _main_kb())
    p = await repo.get_promo(pool, promo_id)
    await _show(
        cb,
        f"Промокод <code>{escape(p['code'])}</code> создан.\n\n{_promo_desc(p)}",
        _main_kb(),
    )
    logger.info(
        f"⚙️ Админ создал промокод #{promo_id} {p['code']} "
        f"({p['kind']}={p['value']}, лимит={p['max_activations']}, фикс={fixes})"
    )


# ── Напоминания (пороги/единица на лету) ─────────────────────────────────────
async def _rem_view(pool: asyncpg.Pool) -> tuple[str, InlineKeyboardBuilder]:
    cfg = await app_settings.reminder_config(pool)
    unit_label = texts.UNIT_LABELS.get(cfg["unit"], cfg["unit"])
    off = cfg["offsets"]
    text = (
        "<b>НАПОМИНАНИЯ О ПРОДЛЕНИИ</b>\n\n"
        f"Единица порогов: <b>{unit_label}</b>\n"
        f"За сколько до конца (в этих единицах):\n"
        f"· раннее «осталось N» — <b>{off['early']}</b>\n"
        f"· «завтра» — <b>{off['soon']}</b>\n"
        f"· «последний день» — <b>{off['last']}</b>\n\n"
        f"Проверка идёт каждые {settings.reminder_check_interval_min} мин "
        "(частота — в .env). Пороги и единица применяются сразу, без рестарта.\n\n"
        "Что меняем?"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"Единица: {unit_label}", callback_data="adm:remunit"))
    b.row(InlineKeyboardButton(text=f"Раннее ({off['early']})", callback_data="adm:remset:early"))
    b.row(InlineKeyboardButton(text=f"«Завтра» ({off['soon']})", callback_data="adm:remset:soon"))
    b.row(InlineKeyboardButton(text=f"Последний день ({off['last']})", callback_data="adm:remset:last"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    return text, b


@router.callback_query(F.data == "adm:rem")
async def adm_rem(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    text, b = await _rem_view(pool)
    await _show(cb, text, b)


@router.callback_query(F.data == "adm:remunit")
async def adm_rem_unit_choose(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await _show(cb, "Выберите единицу порогов напоминаний:", _unit_kb("adm:remu"))


@router.callback_query(F.data.startswith("adm:remu:"))
async def adm_rem_unit_set(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    unit = cb.data.rsplit(":", 1)[1]
    if unit in app_settings.VALID_UNITS:
        await app_settings.set_reminder_unit(pool, unit)
        logger.info(f"⚙️ Админ: единица напоминаний = {unit}")
    text, b = await _rem_view(pool)
    await _show(cb, text, b)


_REM_KIND_LABEL = {"early": "раннее", "soon": "«завтра»", "last": "последний день"}


@router.callback_query(F.data.startswith("adm:remset:"))
async def adm_rem_offset_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    kind = cb.data.rsplit(":", 1)[1]
    await state.set_state(AdminStates.rem_offset)
    await state.update_data(rem_kind=kind)
    await _show(
        cb,
        f"Введите порог для «{_REM_KIND_LABEL[kind]}» — сколько целых единиц "
        "должно остаться до конца (целое число, 0 — последняя единица):",
        _cancel_kb(),
    )


@router.message(AdminStates.rem_offset)
async def adm_rem_offset_set(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("Введите целое число (0 или больше):")
    kind = (await state.get_data())["rem_kind"]
    await app_settings.set_reminder_offset(pool, kind, int(raw))
    await state.clear()
    logger.info(f"⚙️ Админ: порог напоминания {kind} = {raw}")
    text, b = await _rem_view(pool)
    await message.answer(text, reply_markup=b.as_markup())


# ── Ссылка поддержки (кнопка «Перейти» у пользователя) ───────────────────────
def _normalize_support_url(raw: str) -> str | None:
    """Приводит ввод админа к валидному URL для кнопки. None — не распознано.

    @username / голый username → https://t.me/username; t.me/... → https://t.me/...;
    http(s)://… и tg://… — оставляем как есть.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith(("https://", "http://", "tg://")):
        return raw
    if raw.startswith("t.me/"):
        return "https://" + raw
    if raw.startswith("@"):
        raw = raw[1:]
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw):
        return "https://t.me/" + raw
    return None


async def _support_view(pool: asyncpg.Pool) -> tuple[str, InlineKeyboardBuilder]:
    url = await app_settings.support_url(pool)
    if url:
        status = f"Текущая ссылка: <code>{escape(url)}</code>"
    else:
        status = "Ссылка не задана — кнопка «Перейти» у пользователя скрыта."
    text = (
        "<b>ССЫЛКА ПОДДЕРЖКИ</b>\n\n"
        f"{status}\n\n"
        "В разделе «Поддержка» пользователь видит кнопку, ведущую на этот аккаунт. "
        "Применяется сразу, без рестарта."
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Изменить ссылку", callback_data="adm:supportset"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    return text, b


@router.callback_query(F.data == "adm:support")
async def adm_support(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    text, b = await _support_view(pool)
    await _show(cb, text, b)


@router.callback_query(F.data == "adm:supportset")
async def adm_support_set_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.support_url)
    await _show(
        cb,
        "Пришлите ссылку или @username аккаунта поддержки.\n"
        "Примеры: <code>@club_support</code> или <code>https://t.me/club_support</code>",
        _cancel_kb(),
    )


@router.message(AdminStates.support_url)
async def adm_support_set(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(message.from_user.id):
        return
    url = _normalize_support_url(message.text or "")
    if not url:
        return await message.answer(
            "Не похоже на ссылку. Пришлите @username или ссылку вида https://t.me/…:"
        )
    await app_settings.set_support_url(pool, url)
    await state.clear()
    logger.info(f"⚙️ Админ установил ссылку поддержки: {url}")
    text, b = await _support_view(pool)
    await message.answer(text, reply_markup=b.as_markup())


# ── Застрявшие в FSM ─────────────────────────────────────────────────────────
def _ago(dt: datetime, now: datetime) -> str:
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 3600:
        return f"{secs // 60} мин назад"
    if secs < 86400:
        return f"{secs // 3600} ч назад"
    return f"{secs // 86400} дн назад"


@router.callback_query(F.data == "adm:fsm")
async def adm_fsm(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await repo.get_fsm_stuck(pool)
    now = datetime.now(timezone.utc)
    lines = [
        "<b>ЗАСТРЯВШИЕ В FSM</b>",
        "<i>Последний шаг сценария у пользователей (свежие сверху).</i>",
        "",
    ]
    if not rows:
        lines.append("Сейчас никто не в процессе.")
    for r in rows:
        uname = f"@{escape(r['username'])}" if r["username"] else "—"
        name = escape(r["first_name"] or "")
        lines.append(
            f"<code>{r['tg_id']}</code> {uname} {name} · "
            f"<b>{escape(r['state'] or '')}</b> · {_ago(r['updated_at'], now)}"
        )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Обновить", callback_data="adm:fsm"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)


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
    tiers = await repo.get_all_tiers(pool)
    occ = await repo.tier_occupancy(pool)
    lines = [
        "<b>СТАТИСТИКА</b>",
        "",
        f"Активных участников (занято мест): <b>{taken}</b>",
        f"Текущая ставка: {cur}",
        "",
        "<b>Занято по ступеням:</b>",
    ]
    for t in tiers:
        limit = "∞" if t["seat_limit"] is None else str(t["seat_limit"])
        lines.append(
            f"· {escape(t['name'])}: {occ.get(t['id'], 0)} (брекет {limit})"
        )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Назад", callback_data="adm:menu"))
    await _show(cb, "\n".join(lines), b)
