"""Раздел админки «Мероприятия»: CRUD событий и цен по типам билетов."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..db import get_pool
from ..logger import logger
from ..services import events as events_logic
from . import events_repo
from .deps import current_admin, templates

router = APIRouter()

# Типы билетов (порядок = порядок показа в форме). Значение → подпись.
TICKET_TYPES: list[tuple[str, str]] = [
    ("male", "Мужской"),
    ("female", "Женский"),
    ("pair_mf", "Парный М+Ж"),
    ("pair_ff", "Парный Ж+Ж"),
    ("pair_mm", "Парный М+М"),
]
KINDS: list[tuple[str, str]] = [
    ("banya", "Энерго Баня"),
    ("retreat", "Ретрит"),
]
_KIND_LABEL = dict(KINDS)
_TYPE_LABEL = dict(TICKET_TYPES)


def _parse_int(raw: str | None, *, default=None):
    raw = (raw or "").strip()
    if raw == "":
        return default
    return int(raw)


def _defaults_form() -> dict:
    return {
        "id": None, "kind": "banya", "title": "",
        "starts_at": "", "gender_balance": False,
        "seats_total": "", "seats_male": "", "seats_female": "",
        "show_in_advance": False, "subscriber_discount_percent": "0",
        "address": "", "rules_text": "", "is_active": True,
    }


def _form_from_record(rec) -> dict:
    return {
        "id": rec["id"], "kind": rec["kind"], "title": rec["title"],
        "starts_at": rec["starts_at"].strftime("%Y-%m-%dT%H:%M") if rec["starts_at"] else "",
        "gender_balance": rec["gender_balance"],
        "seats_total": "" if rec["seats_total"] is None else rec["seats_total"],
        "seats_male": "" if rec["seats_male"] is None else rec["seats_male"],
        "seats_female": "" if rec["seats_female"] is None else rec["seats_female"],
        "show_in_advance": rec["show_in_advance"],
        "subscriber_discount_percent": rec["subscriber_discount_percent"],
        "address": rec["address"], "rules_text": rec["rules_text"],
        "is_active": rec["is_active"],
    }


def _parse_submit(form) -> tuple[dict, dict, dict, str | None]:
    """Разбирает поданную форму. Возвращает (data, prices, refill, error).

    data    — словарь для events_repo (типизированные значения);
    prices  — {ticket_type: int|None} для set_prices;
    refill  — значения для повторного показа формы при ошибке;
    error   — текст ошибки или None.
    """
    refill = {
        "id": (form.get("id") or "").strip() or None,
        "kind": (form.get("kind") or "banya").strip(),
        "title": (form.get("title") or "").strip(),
        "starts_at": (form.get("starts_at") or "").strip(),
        "gender_balance": form.get("gender_balance") == "on",
        "seats_total": (form.get("seats_total") or "").strip(),
        "seats_male": (form.get("seats_male") or "").strip(),
        "seats_female": (form.get("seats_female") or "").strip(),
        "show_in_advance": form.get("show_in_advance") == "on",
        "subscriber_discount_percent": (form.get("subscriber_discount_percent") or "0").strip(),
        "address": (form.get("address") or "").strip(),
        "rules_text": (form.get("rules_text") or "").strip(),
        "is_active": form.get("is_active") == "on",
    }
    prices_refill = {t: (form.get(f"price_{t}") or "").strip() for t, _ in TICKET_TYPES}
    refill["prices"] = prices_refill

    if refill["kind"] not in _KIND_LABEL:
        return {}, {}, refill, "Выберите тип мероприятия."
    if not refill["title"]:
        return {}, {}, refill, "Укажите название мероприятия."
    if not refill["starts_at"]:
        return {}, {}, refill, "Укажите дату и время."
    try:
        starts_at = datetime.fromisoformat(refill["starts_at"])
    except ValueError:
        return {}, {}, refill, "Некорректная дата/время."

    try:
        seats_total = _parse_int(refill["seats_total"])
        seats_male = _parse_int(refill["seats_male"])
        seats_female = _parse_int(refill["seats_female"])
        discount = _parse_int(refill["subscriber_discount_percent"], default=0)
    except ValueError:
        return {}, {}, refill, "Места и скидка должны быть целыми числами."

    if discount < 0 or discount > 100:
        return {}, {}, refill, "Скидка подписчику — от 0 до 100%."

    # Цены по типам билетов: пусто → тип не продаётся (None), число → цена.
    prices: dict[str, int | None] = {}
    try:
        for ttype, _ in TICKET_TYPES:
            val = _parse_int(prices_refill[ttype])
            if val is not None and val < 0:
                return {}, {}, refill, "Цена не может быть отрицательной."
            prices[ttype] = val
    except ValueError:
        return {}, {}, refill, "Цены должны быть целыми числами."

    if all(v is None for v in prices.values()):
        return {}, {}, refill, "Укажите цену хотя бы для одного типа билета."

    data = {
        "kind": refill["kind"], "title": refill["title"], "starts_at": starts_at,
        "gender_balance": refill["gender_balance"],
        "seats_total": seats_total, "seats_male": seats_male, "seats_female": seats_female,
        "show_in_advance": refill["show_in_advance"],
        "subscriber_discount_percent": discount,
        "address": refill["address"], "rules_text": refill["rules_text"],
        "is_active": refill["is_active"],
    }
    return data, prices, refill, None


# ── Список ───────────────────────────────────────────────────────────────────
@router.get("/events")
async def events_list(request: Request):
    current_admin(request)
    pool = get_pool()
    events = await events_repo.list_events(pool)
    prices = await events_repo.prices_by_event(pool)
    counts = await events_repo.ticket_counts_by_event(pool)
    # Занятые места по событию: {event_id: {male, female, total}} (пара = 2 места).
    occupancy = {eid: events_logic.seats_occupied(c) for eid, c in counts.items()}
    now = datetime.now(timezone.utc)
    upcoming, past = [], []
    for e in events:
        (upcoming if e["starts_at"] >= now else past).append(e)
    return templates.TemplateResponse(
        request, "events_list.html",
        {
            "active": "events", "admin": request.session.get("admin"),
            "upcoming": upcoming, "past": past, "prices": prices,
            "occupancy": occupancy,
            "kind_label": _KIND_LABEL, "type_label": _TYPE_LABEL, "ticket_types": TICKET_TYPES,
        },
    )


# ── Создание ─────────────────────────────────────────────────────────────────
@router.get("/events/new")
async def event_new(request: Request):
    current_admin(request)
    return _render_form(request, _defaults_form(), {}, error=None, is_new=True)


@router.post("/events/new")
async def event_create(request: Request):
    current_admin(request)
    form = await request.form()
    data, prices, refill, error = _parse_submit(form)
    if error:
        return _render_form(request, refill, refill["prices"], error=error, is_new=True, status=400)
    pool = get_pool()
    event_id = await events_repo.create_event(pool, data)
    await events_repo.set_prices(pool, event_id, prices)
    logger.info("Админка: создано мероприятие #{} «{}»", event_id, data["title"])
    return RedirectResponse("/events", status_code=303)


# ── Редактирование ───────────────────────────────────────────────────────────
@router.get("/events/{event_id}/edit")
async def event_edit(request: Request, event_id: int):
    current_admin(request)
    pool = get_pool()
    rec = await events_repo.get_event(pool, event_id)
    if not rec:
        return RedirectResponse("/events", status_code=303)
    prices = await events_repo.get_prices(pool, event_id)
    return _render_form(request, _form_from_record(rec), prices, error=None, is_new=False)


@router.post("/events/{event_id}/edit")
async def event_update(request: Request, event_id: int):
    current_admin(request)
    form = await request.form()
    data, prices, refill, error = _parse_submit(form)
    if error:
        refill["id"] = event_id
        return _render_form(request, refill, refill["prices"], error=error, is_new=False, status=400)
    pool = get_pool()
    await events_repo.update_event(pool, event_id, data)
    await events_repo.set_prices(pool, event_id, prices)
    logger.info("Админка: обновлено мероприятие #{} «{}»", event_id, data["title"])
    return RedirectResponse("/events", status_code=303)


# ── Удаление ─────────────────────────────────────────────────────────────────
@router.post("/events/{event_id}/delete")
async def event_delete(request: Request, event_id: int):
    current_admin(request)
    pool = get_pool()
    await events_repo.delete_event(pool, event_id)
    logger.info("Админка: удалено мероприятие #{}", event_id)
    return RedirectResponse("/events", status_code=303)


# ── Отмена (этап 20) ─────────────────────────────────────────────────────────
@router.post("/events/{event_id}/cancel")
async def event_cancel(request: Request, event_id: int):
    """Отменяет событие: проставляет canceled_at + скрывает. Рассылку купившим и
    пометку билетов на возврат выполнит фоновый джоб бота (отдельный процесс)."""
    current_admin(request)
    pool = get_pool()
    done = await events_repo.cancel_event(pool, event_id)
    if done:
        logger.info("Админка: отменено мероприятие #{} (рассылку выполнит бот)", event_id)
    return RedirectResponse("/events", status_code=303)


def _render_form(request: Request, f: dict, prices: dict, *, error, is_new: bool, status: int = 200):
    return templates.TemplateResponse(
        request, "event_form.html",
        {
            "active": "events", "admin": request.session.get("admin"),
            "f": f, "prices": prices, "error": error, "is_new": is_new,
            "ticket_types": TICKET_TYPES, "kinds": KINDS,
        },
        status_code=status,
    )
