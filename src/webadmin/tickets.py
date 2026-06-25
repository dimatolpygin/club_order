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


async def _render(request: Request, *, event_id: int | None,
                  error: str | None = None, ok: str | None = None, status: int = 200):
    pool = get_pool()
    tickets = await repo.list_sold_tickets(pool, event_id)
    events = await events_repo.list_events(pool)
    return templates.TemplateResponse(
        request, "tickets.html",
        {
            "active": "tickets", "admin": request.session.get("admin"),
            "tickets": tickets, "events": events, "selected_event": event_id,
            "type_label": TICKET_TYPE_LABELS, "kind_label": KIND_LABELS,
            "error": error, "ok": ok,
        },
        status_code=status,
    )


@router.get("/tickets")
async def tickets_page(request: Request):
    current_admin(request)
    raw = request.query_params.get("event_id")
    event_id = int(raw) if raw and raw.strip().isdigit() else None
    return await _render(request, event_id=event_id)


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
