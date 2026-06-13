"""Админ-панель — пошаговый FSM-сценарий с инлайн-меню (этап 2).

Навигация кнопками, ввод значений по шагам («введите цену», «введите лимит»).
Доступ — только для id из ADMIN_IDS. Полный набор функций — этап 8.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from redis.asyncio import Redis

from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..services import subscriptions, tariffs
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
    lines = ["<b>ДЛИТЕЛЬНОСТИ</b>", "Нажми, чтобы включить/выключить:", ""]
    b = InlineKeyboardBuilder()
    for r in rows:
        mark = "✓" if r["is_active"] else "✕"
        label = texts.period_phrase(r["months"], r["unit"])
        lines.append(f"{mark} {label}")
        b.row(InlineKeyboardButton(
            text=f"{mark} {label}",
            callback_data=f"adm:dtoggle:{r['id']}",
        ))
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

    # Статус оплаты (детально) и фактическое членство в группе появятся на этапах 3–4.
    lines.append("")
    lines.append("<i>Детальный статус платежей — с этапа 3, членство в группе — с этапа 4.</i>")
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


# ── Рассылка по базе (без фото) ──────────────────────────────────────────────
@router.callback_query(F.data == "adm:bcaststart")
async def adm_bcast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AdminStates.broadcast_text)
    await _show(
        cb,
        "Рассылка по базе.\n\nОтправьте текст сообщения (HTML-разметка поддерживается):",
        _cancel_kb(),
    )


@router.message(AdminStates.broadcast_text)
async def adm_bcast_preview(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if not text.strip():
        return await message.answer("Пустое сообщение. Отправьте текст рассылки:")
    await state.update_data(bcast_text=text)
    count = len(await repo.get_all_user_ids(pool))
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"Отправить всем ({count})", callback_data="adm:bcast_go"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="adm:menu"))
    await message.answer(
        "<b>Предпросмотр рассылки</b>\n\n" + text + f"\n\n— получателей: {count}",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "adm:bcast_go")
async def adm_bcast_go(
    cb: CallbackQuery, state: FSMContext, bot: Bot, pool: asyncpg.Pool
) -> None:
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    data = await state.get_data()
    text = data.get("bcast_text")
    await state.clear()
    if not text:
        return await _show(cb, "Текст рассылки потерян, начните заново.", _main_kb())

    await cb.answer("Рассылка запущена")
    with suppress(TelegramBadRequest):
        await cb.message.edit_text("Рассылка запущена, отправляю...")

    user_ids = await repo.get_all_user_ids(pool)
    sent = blocked = failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            await repo.set_user_blocked(pool, uid, True)
        except TelegramBadRequest:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/s — не упираемся в лимиты Telegram
    await cb.message.answer(
        f"<b>Рассылка завершена</b>\n\nОтправлено: {sent}\n"
        f"Заблокировали бота: {blocked}\nОшибки: {failed}",
        reply_markup=_main_kb().as_markup(),
    )
    logger.info(f"📣 Рассылка: отправлено {sent}, заблок. {blocked}, ошибок {failed}")


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
