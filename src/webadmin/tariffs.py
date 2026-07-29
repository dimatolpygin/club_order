"""Раздел админки «Тарифы» (этап 23; переработан на этапе 43).

С этапа 43 ступени по числу занятых мест УБРАНЫ. Тариф подписки — ровно две цены
(₽/мес): **вход** (новичок / после перерыва) и **продление** (непрерывный
подписчик). Цены хранятся в bot_settings (services.app_settings), регулировка
стоимости для первых участников — промокодами. Плюс длительности (значение+единица,
добавить/удалить/вкл-выкл) — цена за срок = ставка × значение. При любой правке
инвалидируем Redis-кеш длительностей, поэтому бот применяет изменения без рестарта.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import repo, texts
from ..cache import get_redis
from ..db import get_pool
from ..logger import logger
from ..services import app_settings
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
    prices = await app_settings.subscription_prices(pool)
    durations = await repo.get_all_durations(pool)
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
            "entry_price": fmt_price(prices["entry"]),
            "renewal_price": fmt_price(prices["renewal"]),
            "durations": dur_rows, "units": UNITS,
            "ok": ok, "error": error,
        },
    )


@router.get("/tariffs")
async def tariffs_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


# ── Две цены: вход и продление (этап 43) ─────────────────────────────────────
@router.post("/tariffs/prices")
async def prices_save(request: Request):
    current_admin(request)
    pool = get_pool()
    form = await request.form()
    try:
        entry = _parse_price(form.get("entry_price"))
        renewal = _parse_price(form.get("renewal_price"))
        if entry is None or renewal is None:
            raise ValueError("цена")
    except ValueError:
        return await _overview(
            request, error="Цены входа и продления — числа больше нуля."
        )
    await app_settings.set_subscription_price(pool, "entry", entry)
    await app_settings.set_subscription_price(pool, "renewal", renewal)
    await tariffs_svc.invalidate(get_redis())
    logger.info(
        "Админка: цены подписки сохранены — вход {}, продление {}", entry, renewal
    )
    return RedirectResponse("/tariffs?ok=Цены сохранены.", status_code=303)


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


@router.post("/tariffs/durations/{dur_id}/move")
async def duration_move(request: Request, dur_id: int):
    current_admin(request)
    form = await request.form()
    direction = (form.get("dir") or "").strip()
    if direction not in ("up", "down"):
        return RedirectResponse("/tariffs", status_code=303)
    pool = get_pool()
    if await repo.move_duration(pool, dur_id, direction):
        await tariffs_svc.invalidate(get_redis())
        logger.info("Админка: длительность #{} сдвинута {}", dur_id, direction)
    return RedirectResponse("/tariffs?ok=Порядок обновлён.", status_code=303)


@router.post("/tariffs/durations/{dur_id}/delete")
async def duration_delete(request: Request, dur_id: int):
    current_admin(request)
    pool = get_pool()
    if await repo.delete_duration(pool, dur_id):
        await tariffs_svc.invalidate(get_redis())
        logger.info("Админка: удалена длительность #{}", dur_id)
    return RedirectResponse("/tariffs?ok=Длительность удалена.", status_code=303)
