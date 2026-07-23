"""Раздел «Мои билеты» + запрос на возврат (этап 18).

«Мои билеты» — список активных билетов пользователя (оплаченные на будущие события;
прошедшие скрыты). Карточка билета: данные заказа, показ адреса (через существующий
флоу согласия с правилами, обработчик TAGREE в handlers/events.py) и запрос на возврат.

Возврат — только вручную через менеджера (решение заказчика): по подтверждению заявка
с данными билета уходит всем админам/менеджерам. Статус билета НЕ меняем — место не
освобождаем до фактического возврата. Кнопки «Перенос» нет.
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import admin_alerts
from ..services import app_settings
from ..services import events as ev
from ..utils import fmt_price

router = Router()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    # Текущее сообщение может быть фото (инфо-экран с картинкой, этап 37): по фото
    # edit_text невозможен — заменяем сообщение (удаляем и шлём заново).
    if cb.message.photo:
        with suppress(TelegramBadRequest):
            await cb.message.delete()
        await cb.message.answer(text, reply_markup=markup)
    else:
        with suppress(TelegramBadRequest):  # «message is not modified» — не критично
            await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ── Список активных билетов ──────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_MYTICKETS)
async def show_my_tickets(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:mytickets")
    tickets = await repo.list_active_tickets(pool, cb.from_user.id)
    if not tickets:
        await _edit(cb, texts.MY_TICKETS_NONE, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: мои билеты (пусто)")
        return
    await _edit(cb, texts.my_tickets_list(len(tickets)), kb.my_tickets_kb(tickets))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: мои билеты — {len(tickets)} активн."
    )


async def _owned_ticket(
    cb: CallbackQuery, pool: asyncpg.Pool, ticket_id: int
) -> asyncpg.Record | None:
    """Билет пользователя в статусе 'paid' или None (с попапом-объяснением).

    Посещённый билет (отмечен приход на входе, этап 34) считается использованным:
    карточка/возврат по нему недоступны — даже если пользователь жмёт по старой кнопке
    из ранее открытого сообщения.
    """
    ticket = await repo.get_ticket(pool, ticket_id)
    if ticket is None or ticket["tg_id"] != cb.from_user.id or ticket["status"] != "paid":
        await cb.answer("Билет не найден.", show_alert=True)
        return None
    if ticket["attended_at"] is not None:
        await cb.answer(
            "Этот билет уже использован (отмечен на входе) — возврат недоступен.",
            show_alert=True,
        )
        return None
    return ticket


# ── Карточка билета ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.MYT_OPEN}:"))
async def open_ticket(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    ticket_id = int(cb.data.split(":", 1)[1])
    ticket = await _owned_ticket(cb, pool, ticket_id)
    if ticket is None:
        return
    event = await repo.get_event(pool, ticket["event_id"])
    if event is None:
        await cb.answer("Событие не найдено.", show_alert=True)
        return
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:myticket:{ticket_id}")
    refund_requested = ticket["refund_requested"]
    text = texts.ticket_detail(
        event["title"], ev.kind_label(event["kind"]),
        ev.ticket_label(ticket["ticket_type"]), event["starts_at"],
        fmt_price(ticket["price"]),
        rules_text=event["rules_text"], address=event["address"],
        refund_requested=refund_requested, ticket_id=ticket_id,
    )
    await _edit(cb, text, kb.ticket_detail_kb(ticket_id, refund_requested))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: карточка билета #{ticket_id}"
        f"{' (возврат запрошен)' if refund_requested else ''}"
    )


# ── Запрос на возврат: подтверждение ─────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.MYT_REFUND}:"))
async def refund_confirm(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    ticket_id = int(cb.data.split(":", 1)[1])
    ticket = await _owned_ticket(cb, pool, ticket_id)
    if ticket is None:
        return
    if ticket["refund_requested"]:
        await cb.answer("Запрос на возврат уже отправлен — менеджер свяжется.", show_alert=True)
        return
    event = await repo.get_event(pool, ticket["event_id"])
    if event is None:
        await cb.answer("Событие не найдено.", show_alert=True)
        return
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:myticket:refund:{ticket_id}")
    text = texts.ticket_refund_confirm(
        event["title"], ev.ticket_label(ticket["ticket_type"]), event["starts_at"]
    )
    await _edit(cb, text, kb.ticket_refund_confirm_kb(ticket_id))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: подтверждение возврата билета #{ticket_id}"
    )


# ── Запрос на возврат: отправка менеджеру/админам ────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.MYT_REFUND_OK}:"))
async def refund_send(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    ticket_id = int(cb.data.split(":", 1)[1])
    ticket = await _owned_ticket(cb, pool, ticket_id)
    if ticket is None:
        return
    event = await repo.get_event(pool, ticket["event_id"])
    if event is None:
        await cb.answer("Событие не найдено.", show_alert=True)
        return

    # Ставим пометку «возврат запрошен» (статус билета не меняем — место занято).
    # Идемпотентно: если запрос уже стоял, повторно админов не дёргаем.
    newly = await repo.request_ticket_refund(pool, ticket_id, cb.from_user.id)
    if not newly:
        await cb.answer("Запрос на возврат уже отправлен ранее.", show_alert=True)
        await repo.set_fsm_state(pool, cb.from_user.id, f"screen:myticket:refund:sent:{ticket_id}")
        await _edit(cb, texts.TICKET_REFUND_SENT, kb.to_menu_kb())
        return

    notice = texts.ticket_refund_admin_notice(
        username=cb.from_user.username,
        user_id=cb.from_user.id,
        first_name=cb.from_user.first_name,
        title=event["title"],
        ticket_label=ev.ticket_label(ticket["ticket_type"]),
        starts_at=event["starts_at"],
        price=fmt_price(ticket["price"]),
        ticket_id=ticket_id,
    )
    sent = await admin_alerts.notify_admins(bot, notice)
    # Статус билета НЕ меняем — возврат ручной, место не освобождаем до факта возврата.
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:myticket:refund:sent:{ticket_id}")
    if sent > 0:
        await _edit(cb, texts.TICKET_REFUND_SENT, kb.to_menu_kb())
        logger.info(
            f"🎟 Запрос на возврат билета #{ticket_id} от @{cb.from_user.username or '—'} "
            f"(id:{cb.from_user.id}) → отправлен {sent} админ(ам)"
        )
    else:
        await _edit(cb, texts.TICKET_REFUND_NO_ADMINS, kb.support_kb(
            await app_settings.support_url(pool) or None
        ))
        logger.warning(
            f"🎟 Запрос на возврат билета #{ticket_id} — некому отправить (нет админов)"
        )
