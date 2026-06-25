"""Раздел админки «Подписки» (этап 19).

Список активных подписок со сроками, ручное продление (на N единиц) и отключение.
Веб-процесс отдельный от бота: продление/отключение — это запись в общую БД, а
фактический кик из группы при отключении делает фоновая проверка окончаний бота
(см. repo.disable_subscription_via_expiry). Данные читаем из общего слоя repo.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..utils import add_period
from .deps import current_admin, templates

router = APIRouter()

# Единицы продления (как у длительностей бота).
UNIT_LABELS = {"month": "мес.", "day": "дн.", "hour": "ч.", "minute": "мин."}
VALID_UNITS = tuple(UNIT_LABELS)


async def _render(request: Request, *, error: str | None = None, ok: str | None = None,
                  status: int = 200):
    pool = get_pool()
    rows = await repo.list_active_subscriptions(pool)
    now = datetime.now(timezone.utc)
    subs = []
    for r in rows:
        left = r["end_date"] - now
        subs.append({
            "id": r["id"],
            "tg_id": r["tg_id"],
            "username": r["username"],
            "first_name": r["first_name"],
            "fixed_price": r["fixed_price"],
            "end_date": r["end_date"],
            "source": r["source"],
            "days_left": max(0, left.days),
        })
    return templates.TemplateResponse(
        request, "subscriptions.html",
        {
            "active": "subscriptions", "admin": request.session.get("admin"),
            "subs": subs, "unit_labels": UNIT_LABELS,
            "error": error, "ok": ok,
        },
        status_code=status,
    )


@router.get("/subscriptions")
async def subscriptions_page(request: Request):
    current_admin(request)
    return await _render(request)


@router.post("/subscriptions/extend")
async def subscriptions_extend(
    request: Request,
    sub_id: str = Form(...),
    value: str = Form(...),
    unit: str = Form(...),
):
    current_admin(request)
    try:
        sid = int((sub_id or "").strip())
        n = int((value or "").strip())
    except ValueError:
        return await _render(request, error="Срок продления — целое число.", status=400)
    if n <= 0:
        return await _render(request, error="Срок продления должен быть больше нуля.", status=400)
    if unit not in VALID_UNITS:
        return await _render(request, error="Неизвестная единица срока.", status=400)

    pool = get_pool()
    sub = await repo.get_subscription(pool, sid)
    if sub is None or sub["status"] != "active":
        return await _render(request, error="Подписка не найдена или уже неактивна.", status=400)
    new_end = add_period(sub["end_date"], n, unit)
    await repo.set_subscription_end_date(pool, sid, new_end)
    logger.info(
        "Админка: подписка #{} продлена на {} {} (до {:%d.%m.%Y %H:%M}) для id={}",
        sid, n, unit, new_end, sub["tg_id"],
    )
    return await _render(
        request,
        ok=f"Подписка #{sid} продлена на {n} {UNIT_LABELS[unit]} — до "
           f"{new_end:%d.%m.%Y %H:%M}.",
    )


@router.post("/subscriptions/disable")
async def subscriptions_disable(request: Request, sub_id: str = Form(...)):
    current_admin(request)
    try:
        sid = int((sub_id or "").strip())
    except ValueError:
        return await _render(request, error="Некорректный идентификатор подписки.", status=400)
    pool = get_pool()
    tg_id = await repo.disable_subscription_via_expiry(pool, sid)
    if tg_id is None:
        return await _render(request, error="Подписка не найдена или уже неактивна.", status=400)
    logger.info("Админка: подписка #{} отключена вручную (id={})", sid, tg_id)
    return await _render(
        request,
        ok=f"Подписка #{sid} отключена. Доступ закрыт; бот удалит участника из группы "
           f"на ближайшей проверке окончаний.",
    )
