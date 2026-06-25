"""Раздел админки «Тарифы» (этап 23) — перенос из бот-команды /admin.

Ценовые ступени (ставка ₽/мес, лимит мест-брекета, название, вкл/выкл), матрица цен
за периоды (3/6/12… — своя цена или авто = ставка×значение) и длительности
(значение+единица, добавить/удалить/вкл-выкл). Логику и хранение переиспользуем из
`repo`/`services.tariffs`; при любой правке инвалидируем Redis-кеш тарифов, поэтому бот
применяет изменения без рестарта (кеш TTL 300с — инвалидация даёт мгновенный эффект).
Ступени не создаются/не удаляются (фиксированный набор брекетов) — только правятся.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import repo, texts
from ..cache import get_redis
from ..db import get_pool
from ..logger import logger
from ..services import tariffs as tariffs_svc
from ..utils import fmt_price
from .deps import current_admin, templates

router = APIRouter()

# Единицы длительности (значение → подпись), порядок = порядок в форме.
UNITS: list[tuple[str, str]] = [
    ("month", "Месяц"), ("day", "День"), ("hour", "Час"), ("minute", "Минута"),
]
_UNIT_KEYS = {u for u, _ in UNITS}


def _parse_price(raw: str | None) -> Decimal | None:
    """Цена из строки (запятая/точка). Пусто → None; некорректная/≤0 → ValueError."""
    raw = (raw or "").replace(",", ".").strip()
    if raw == "":
        return None
    try:
        price = Decimal(raw)
    except InvalidOperation:
        raise ValueError("цена")
    if price <= 0:
        raise ValueError("цена")
    return price


async def _overview(request: Request, *, ok: str | None = None, error: str | None = None):
    pool = get_pool()
    tiers = await repo.get_all_tiers(pool)
    occ = await repo.tier_occupancy(pool)
    durations = await repo.get_all_durations(pool)
    tier_rows = [
        {
            "id": t["id"], "name": t["name"],
            "monthly_price": fmt_price(t["monthly_price"]),
            "seat_limit": "безлимит" if t["seat_limit"] is None else t["seat_limit"],
            "is_active": t["is_active"], "occupied": occ.get(t["id"], 0),
        }
        for t in tiers
    ]
    dur_rows = [
        {
            "id": d["id"], "label": texts.period_phrase(d["months"], d["unit"]),
            "is_active": d["is_active"],
        }
        for d in durations
    ]
    return templates.TemplateResponse(
        request, "tariffs.html",
        {
            "active": "tariffs", "admin": request.session.get("admin"),
            "tiers": tier_rows, "durations": dur_rows, "units": UNITS,
            "ok": ok, "error": error,
        },
    )


@router.get("/tariffs")
async def tariffs_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


# ── Ступень: форма правки + цены за периоды ──────────────────────────────────
async def _tier_form(request: Request, tier_id: int, *, error: str | None = None, ok: bool = False):
    pool = get_pool()
    t = await repo.get_tier(pool, tier_id)
    if t is None:
        return RedirectResponse("/tariffs", status_code=303)
    monthly = t["monthly_price"]
    durations = await repo.get_active_durations(pool)
    overrides = await repo.get_tier_prices(pool, tier_id)
    # Цену за период задаём для всех активных длительностей, кроме канонического
    # «1 месяц» (он равен ставке). Остальные: своя цена или авто = ставка×значение.
    periods = []
    for d in durations:
        if d["months"] == 1 and d["unit"] == "month":
            continue
        key = (d["months"], d["unit"])
        custom = key in overrides
        periods.append({
            "field": f"price_{d['months']}_{d['unit']}",
            "label": texts.period_phrase(d["months"], d["unit"]),
            "value": fmt_price(overrides[key]) if custom else "",
            "auto": fmt_price(monthly * d["months"]),
            "custom": custom,
        })
    tier = {
        "id": t["id"], "name": t["name"],
        "monthly_price": fmt_price(monthly),
        "seat_limit": "" if t["seat_limit"] is None else t["seat_limit"],
        "is_active": t["is_active"],
    }
    return templates.TemplateResponse(
        request, "tier_form.html",
        {
            "active": "tariffs", "admin": request.session.get("admin"),
            "tier": tier, "periods": periods, "error": error, "ok": ok,
        },
    )


@router.get("/tariffs/tier/{tier_id}")
async def tier_form_page(request: Request, tier_id: int, ok: int = 0):
    current_admin(request)
    return await _tier_form(request, tier_id, ok=bool(ok))


@router.post("/tariffs/tier/{tier_id}")
async def tier_save(request: Request, tier_id: int):
    current_admin(request)
    pool = get_pool()
    t = await repo.get_tier(pool, tier_id)
    if t is None:
        return RedirectResponse("/tariffs", status_code=303)
    form = await request.form()

    name = (form.get("name") or "").strip()
    if not name:
        return await _tier_form(request, tier_id, error="Название не может быть пустым.")
    try:
        monthly = _parse_price(form.get("monthly_price"))
        if monthly is None:
            raise ValueError("ставка")
    except ValueError:
        return await _tier_form(request, tier_id, error="Ставка ₽/мес — число больше нуля.")

    seat_raw = (form.get("seat_limit") or "").strip()
    if seat_raw == "" or seat_raw == "0":
        seat_limit = None  # пусто/0 → безлимит
    elif seat_raw.isdigit():
        seat_limit = int(seat_raw)
    else:
        return await _tier_form(request, tier_id, error="Лимит мест — целое число (пусто или 0 — безлимит).")

    is_active = form.get("is_active") is not None

    # Цены за периоды: пусто → авто (удаляем переопределение), число → своя цена.
    period_updates: list[tuple[int, str, Decimal | None]] = []
    for dur in await repo.get_active_durations(pool):
        if dur["months"] == 1 and dur["unit"] == "month":
            continue
        field = f"price_{dur['months']}_{dur['unit']}"
        if field not in form:
            continue
        try:
            price = _parse_price(form.get(field))
        except ValueError:
            return await _tier_form(
                request, tier_id,
                error=f"Цена за «{texts.period_phrase(dur['months'], dur['unit'])}» — число больше нуля или пусто.",
            )
        period_updates.append((dur["months"], dur["unit"], price))

    await repo.update_tier(
        pool, tier_id, name=name, monthly_price=monthly,
        seat_limit=seat_limit, is_active=is_active,
    )
    for months, unit, price in period_updates:
        if price is None:
            await repo.delete_tier_price(pool, tier_id, months, unit)
        else:
            await repo.set_tier_price(pool, tier_id, months, unit, price)

    await tariffs_svc.invalidate(get_redis())
    logger.info("Админка: ступень #{} сохранена (тарифы)", tier_id)
    return RedirectResponse(f"/tariffs/tier/{tier_id}?ok=1", status_code=303)


# ── Длительности ─────────────────────────────────────────────────────────────
@router.post("/tariffs/durations/add")
async def duration_add(request: Request):
    current_admin(request)
    form = await request.form()
    raw = (form.get("value") or "").strip()
    unit = (form.get("unit") or "").strip()
    if not raw.isdigit() or int(raw) <= 0 or unit not in _UNIT_KEYS:
        return RedirectResponse("/tariffs?error=Длительность: целое число и единица.", status_code=303)
    pool = get_pool()
    await repo.upsert_duration(pool, int(raw), unit, True)
    await tariffs_svc.invalidate(get_redis())
    logger.info("Админка: добавлена длительность {} {}", raw, unit)
    return RedirectResponse("/tariffs?ok=Длительность добавлена.", status_code=303)


@router.post("/tariffs/durations/{dur_id}/toggle")
async def duration_toggle(request: Request, dur_id: int):
    current_admin(request)
    pool = get_pool()
    cur = await repo.get_duration(pool, dur_id)
    if cur is not None:
        await repo.set_duration_active(pool, dur_id, not cur["is_active"])
        await tariffs_svc.invalidate(get_redis())
        logger.info("Админка: длительность #{} active={}", dur_id, not cur["is_active"])
    return RedirectResponse("/tariffs?ok=Сохранено.", status_code=303)


@router.post("/tariffs/durations/{dur_id}/delete")
async def duration_delete(request: Request, dur_id: int):
    current_admin(request)
    pool = get_pool()
    if await repo.delete_duration(pool, dur_id):
        await tariffs_svc.invalidate(get_redis())
        logger.info("Админка: удалена длительность #{}", dur_id)
    return RedirectResponse("/tariffs?ok=Длительность удалена.", status_code=303)
