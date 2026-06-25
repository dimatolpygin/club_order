"""Раздел админки «Билеты» (этап 21).

Список проданных билетов (фильтр по событию) и отметка фактического возврата
менеджером. Деньги возвращаются вручную переводом — админка фиксирует факт:
статус билета → 'refunded' (аудит кто/когда). Перевод освобождает место (занятость
считается по 'paid') и убирает билет из «Моих билетов». Мутации — через общий
src.repo (с void реф-связи в одной транзакции), список — оттуда же.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from . import events_repo
from .deps import current_admin, templates

router = APIRouter()

TICKET_TYPE_LABELS = {
    "male": "Мужской",
    "female": "Женский",
    "pair_mf": "Парный М+Ж",
    "pair_ff": "Парный Ж+Ж",
    "pair_mm": "Парный М+М",
}
KIND_LABELS = {"banya": "Энерго Баня", "retreat": "Ретрит"}


async def _render(request: Request, *, event_id: int | None, open_thread: int | None = None,
                  error: str | None = None, ok: str | None = None, status: int = 200):
    pool = get_pool()
    tickets = await repo.list_sold_tickets(pool, event_id)
    events = await events_repo.list_events(pool)
    # Переписка для раскрытой карточки (по tg_id билета). Открытие = прочтение входящих.
    thread = []
    if open_thread is not None:
        t = next((x for x in tickets if x["id"] == open_thread), None)
        if t is not None:
            await repo.mark_inbound_read(pool, t["tg_id"])
            thread = await repo.manager_thread(pool, t["tg_id"])
    unread = await repo.unread_inbound_by_user(pool)
    return templates.TemplateResponse(
        request, "tickets.html",
        {
            "active": "tickets", "admin": request.session.get("admin"),
            "tickets": tickets, "events": events, "selected_event": event_id,
            "type_label": TICKET_TYPE_LABELS, "kind_label": KIND_LABELS,
            "open_thread": open_thread, "thread": thread, "unread": unread,
            "total_unread": sum(unread.values()),
            "error": error, "ok": ok,
        },
        status_code=status,
    )


@router.get("/tickets")
async def tickets_page(request: Request):
    current_admin(request)
    raw = request.query_params.get("event_id")
    event_id = int(raw) if raw and raw.strip().isdigit() else None
    raw_t = request.query_params.get("thread")
    open_thread = int(raw_t) if raw_t and raw_t.strip().isdigit() else None
    return await _render(request, event_id=event_id, open_thread=open_thread)


@router.post("/tickets/{ticket_id}/message")
async def ticket_message(
    request: Request, ticket_id: int,
    text: str = Form(...), event_id: str = Form(""),
):
    admin = current_admin(request)
    eid = int(event_id) if event_id and event_id.strip().isdigit() else None
    body = (text or "").strip()
    pool = get_pool()
    ticket = await repo.get_ticket(pool, ticket_id)
    if ticket is None:
        return await _render(request, event_id=eid, error=f"Билет #{ticket_id} не найден.",
                             status=400)
    if not body:
        return await _render(request, event_id=eid, open_thread=ticket_id,
                             error="Введите текст сообщения.", status=400)
    await repo.queue_manager_message(pool, ticket["tg_id"], ticket_id, admin["login"], body)
    logger.info(
        "Админка: сообщение покупателю id={} поставлено в очередь ({})",
        ticket["tg_id"], admin["login"],
    )
    return await _render(
        request, event_id=eid, open_thread=ticket_id,
        ok="Сообщение поставлено в очередь — бот доставит его покупателю в течение минуты. "
           "Если доставить не выйдет (юзер заблокировал бота), статус станет «не доставлено».",
    )


@router.post("/tickets/{ticket_id}/refund")
async def ticket_refund(request: Request, ticket_id: int, event_id: str = Form("")):
    admin = current_admin(request)
    eid = int(event_id) if event_id and event_id.strip().isdigit() else None
    pool = get_pool()
    res = await repo.mark_ticket_refunded(pool, ticket_id, admin["login"])
    if res is None:
        return await _render(
            request, event_id=eid,
            error=f"Билет #{ticket_id} не найден или уже возвращён.", status=400,
        )
    note = " Реф-связь аннулирована (бонус не начислится)." if res["referral_voided"] else ""
    logger.info(
        "Админка: возврат билета #{} отмечен ({}) для id={}{}",
        ticket_id, admin["login"], res["tg_id"],
        " + void реф-связи" if res["referral_voided"] else "",
    )
    return await _render(
        request, event_id=eid,
        ok=f"Билет #{ticket_id} отмечен возвращённым. Место освобождено, билет убран "
           f"из «Моих билетов» у пользователя.{note}",
    )
