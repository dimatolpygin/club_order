"""Раздел «Мероприятия» в боте (этап 13): показ событий + выбор билета.

Поверх данных этапа 12 (`events` + `event_ticket_prices`). Правила показа и
доступность мест — в services.events (чистая логика, покрыта smoke-тестом).
Оплата билета и учёт проданных мест — этап 14.
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import app_settings
from ..services import events as ev
from ..utils import fmt_price

router = Router()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    with suppress(TelegramBadRequest):  # «message is not modified» — не критично
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ── Список мероприятий ───────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_EVENTS)
async def show_events(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:events")

    rows = await repo.list_events(pool)
    visible = ev.visible_events(rows, datetime.now(timezone.utc))
    if not visible:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: мероприятия (пусто)")
        return

    await _edit(cb, texts.EVENTS_LIST, kb.events_list_kb(visible))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: мероприятия — {len(visible)} событ."
    )


# ── Карточка события: меню типов билетов ─────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.EVT_OPEN}:"))
async def show_event(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    event_id = int(cb.data.split(":", 1)[1])
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:event:{event_id}")
    prices = await repo.get_event_prices(pool, event_id)
    # Занятость по проданным билетам — этап 14; пока считаем места по конфигу.
    items = ev.seat_availability(event, prices)

    # Ни одного типа со свободными местами (или вовсе без цен) → «Мест нет».
    if not any(available for _, _, available in items):
        url = await app_settings.support_url(pool)
        await _edit(cb, texts.EVENT_SOLD_OUT, kb.event_sold_out_kb(url or None))
        logger.info(
            f"🤖 Бот → @{cb.from_user.username or '—'}: событие «{event['title']}» — мест нет"
        )
        return

    text = texts.event_card(ev.kind_label(event["kind"]), event["title"], event["starts_at"])
    await _edit(cb, text, kb.event_tickets_kb(event_id, items))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: событие «{event['title']}», "
        f"{len(items)} тип(ов) билетов"
    )


# ── Тап по типу без мест ─────────────────────────────────────────────────────
@router.callback_query(F.data == kb.EVT_FULL)
async def ticket_sold_out(cb: CallbackQuery) -> None:
    await cb.answer("Мест нет. Напиши в поддержку — подскажем по свободным местам.", show_alert=True)


# ── Выбор билета: сводка (оплата — этап 14) ──────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.EVT_BUY}:"))
async def choose_ticket(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    _, event_id_raw, ttype = cb.data.split(":", 2)
    event_id = int(event_id_raw)
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return

    prices = await repo.get_event_prices(pool, event_id)
    # Повторно проверяем доступность типа (мог распродаться между экранами).
    if ttype not in prices or not ev.has_seats(event, ttype):
        await cb.answer("Мест нет на этот тип билета.", show_alert=True)
        return

    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:ticket:{event_id}:{ttype}")
    text = texts.event_ticket_summary(
        event["title"], ev.ticket_label(ttype), fmt_price(prices[ttype])
    )
    await _edit(cb, text, kb.event_ticket_summary_kb(event_id))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: выбран билет {ttype} на "
        f"«{event['title']}» — {fmt_price(prices[ttype])} ₽"
    )
