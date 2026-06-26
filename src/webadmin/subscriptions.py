"""Раздел админки «Подписки» (этап 19) + участники (этап 25).

Список активных подписок со сроками, ручное продление (на N единиц) и отключение.
Этап 25 расширяет раздел работой с участником: поиск по tg_id → карточка статуса
(подписка/доступ/цена/даты) + история действий, ручное добавление оплатившего
(создаёт активную подписку source='manual') и аннулирование с киком.

Веб-процесс отдельный от бота: продление/отключение/аннулирование — это запись в
общую БД, а фактический кик из группы делает фоновая проверка окончаний бота
(repo.disable_subscription_via_expiry — механизм этапа 19: end_date=now() → бот кикает
на ближайшем проходе). Ручную добавленную подписку бот применяет при join-request
(проверяет активную подписку). Данные читаем/пишем через общий слой repo.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo, texts
from ..cache import get_redis
from ..db import get_pool
from ..logger import logger
from ..services import tariffs as tariffs_svc
from ..utils import add_period, fmt_price
from .deps import current_admin, templates

router = APIRouter()

# Единицы продления (как у длительностей бота).
UNIT_LABELS = {"month": "мес.", "day": "дн.", "hour": "ч.", "minute": "мин."}
VALID_UNITS = tuple(UNIT_LABELS)

_SOURCE_LABELS = {"payment": "оплата", "manual": "вручную", "promo": "промокод"}


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


# ── Участники (этап 25): поиск / карточка / история / добавление / аннулирование ──
def _sub_view(sub) -> dict:
    """Подписка → словарь с готовыми подписями для карточки участника."""
    now = datetime.now(timezone.utc)
    return {
        "id": sub["id"],
        "price": f"{fmt_price(sub['fixed_price'])} ₽/мес",
        "period": texts.period_phrase(sub["months"], sub["unit"]),
        "start": sub["start_date"].strftime("%d.%m.%Y · %H:%M"),
        "end": sub["end_date"].strftime("%d.%m.%Y · %H:%M"),
        "remaining": texts.remaining_phrase(sub["end_date"], now, sub["unit"]),
        "status": sub["status"],
        "source": _SOURCE_LABELS.get(sub["source"], sub["source"]),
    }


async def _member_card(request: Request, tg_id: int, *, ok: str | None = None,
                       error: str | None = None, status: int = 200):
    pool = get_pool()
    user = await repo.get_user(pool, tg_id)
    active = await repo.get_active_subscription(pool, tg_id)
    last = await repo.get_last_subscription(pool, tg_id)
    events = await repo.get_user_events(pool, tg_id, limit=20)
    now = datetime.now(timezone.utc)

    member = {
        "tg_id": tg_id,
        "found": not (user is None and last is None),
        "username": user["username"] if user else None,
        "first_name": user["first_name"] if user else None,
        "email": user["email"] if user else None,
        "is_blocked": user["is_blocked"] if user else False,
        "has_active": active is not None,
        "active": _sub_view(active) if active is not None else None,
        "last": _sub_view(last) if last is not None else None,
    }
    history = [
        {"event": e["event"], "when": e["created_at"].strftime("%d.%m.%Y · %H:%M")}
        for e in events
    ]
    return templates.TemplateResponse(
        request, "member.html",
        {
            "active": "subscriptions", "admin": request.session.get("admin"),
            "member": member, "history": history, "unit_labels": UNIT_LABELS,
            "ok": ok, "error": error,
        },
        status_code=status,
    )


@router.get("/subscriptions/find")
async def member_find(request: Request, tg_id: str = ""):
    current_admin(request)
    raw = (tg_id or "").strip()
    if not raw.lstrip("-").isdigit():
        return await _render(request, error="Введите числовой Telegram ID участника.",
                             status=400)
    return RedirectResponse(f"/subscriptions/member/{int(raw)}", status_code=303)


@router.get("/subscriptions/member/{tg_id}")
async def member_page(request: Request, tg_id: int, ok: str | None = None,
                      error: str | None = None):
    current_admin(request)
    return await _member_card(request, tg_id, ok=ok, error=error)


@router.post("/subscriptions/member/add")
async def member_add(
    request: Request,
    tg_id: str = Form(...),
    value: str = Form(...),
    unit: str = Form(...),
):
    current_admin(request)
    raw_id = (tg_id or "").strip()
    if not raw_id.lstrip("-").isdigit():
        return await _render(request, error="Telegram ID участника — это число.", status=400)
    mid = int(raw_id)
    try:
        n = int((value or "").strip())
    except ValueError:
        return await _member_card(request, mid, error="Срок — целое число.", status=400)
    if n <= 0:
        return await _member_card(request, mid, error="Срок должен быть больше нуля.", status=400)
    if unit not in VALID_UNITS:
        return await _member_card(request, mid, error="Неизвестная единица срока.", status=400)

    pool = get_pool()
    tier = await tariffs_svc.get_current_tier(pool, get_redis())
    if tier is None:
        return await _member_card(
            request, mid,
            error="Не удалось определить текущую ставку (нет активных ступеней).",
            status=400,
        )
    await repo.upsert_user(pool, mid, None, None)
    end_date = add_period(datetime.now(timezone.utc), n, unit)
    sub_id = await repo.add_subscription(
        pool, mid, tier["id"], tier["monthly_price"], n, end_date,
        source="manual", status="active", unit=unit,
    )
    logger.info(
        "Админка: вручную добавлена подписка #{} для id={} ({} {}, до {:%d.%m.%Y %H:%M})",
        sub_id, mid, n, unit, end_date,
    )
    msg = (
        f"Подписка #{sub_id} создана: {fmt_price(tier['monthly_price'])} ₽/мес · "
        f"{texts.period_phrase(n, unit)}, до {end_date:%d.%m.%Y %H:%M}. "
        f"Бот пустит участника в группу по заявке на вступление."
    )
    return RedirectResponse(f"/subscriptions/member/{mid}?ok={msg}", status_code=303)


@router.post("/subscriptions/member/{tg_id}/annul")
async def member_annul(request: Request, tg_id: int):
    current_admin(request)
    pool = get_pool()
    active = await repo.get_active_subscription(pool, tg_id)
    if active is None:
        return await _member_card(
            request, tg_id, error="У участника нет активной подписки.", status=400
        )
    await repo.disable_subscription_via_expiry(pool, active["id"])
    logger.info("Админка: подписка #{} аннулирована (id={})", active["id"], tg_id)
    msg = (
        f"Подписка #{active['id']} аннулирована. Доступ закрыт; бот удалит участника "
        f"из группы на ближайшей проверке окончаний."
    )
    return RedirectResponse(f"/subscriptions/member/{tg_id}?ok={msg}", status_code=303)
