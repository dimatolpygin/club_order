"""Раздел админки «Промокоды» (этап 24) — перенос из бот-команды /admin.

Список промокодов подписки, создание (тип fixed_price/percent, значение, лимит
активаций, срок действия, фиксация цены), вкл/выкл, удаление. Логику и хранение
переиспользуем из `repo`/`services.promo` — тот же источник истины, что у бота.
Бот валидирует код напрямую из БД при каждом применении (без Redis-кеша), поэтому
правки из веба действуют сразу, инвалидация кеша не нужна. Все POST — через
PRG-redirect (обновление страницы не повторяет действие).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..services import promo as promo_service
from ..utils import fmt_price
from .deps import current_admin, templates

router = APIRouter()


def _promo_view(p) -> dict:
    """Запись промокода → словарь для шаблона (готовые подписи условий)."""
    if p["kind"] == promo_service.KIND_PERCENT:
        cond = f"скидка {fmt_price(p['value'])}%"
    else:
        cond = f"спец {fmt_price(p['value'])} ₽/мес"
    limit = "∞" if p["max_activations"] is None else str(p["max_activations"])
    expiry = "бессрочно" if p["expires_at"] is None else f"{p['expires_at']:%d.%m.%Y}"
    return {
        "id": p["id"],
        "code": p["code"],
        "cond": cond,
        "used": f"{p['used_count']}/{limit}",
        "expiry": expiry,
        "fix": "фикс" if p["fixes_price"] else "разово",
        "is_active": p["is_active"],
    }


async def _overview(request: Request, *, ok: str | None = None, error: str | None = None):
    pool = get_pool()
    promos = await repo.get_all_promos(pool)
    return templates.TemplateResponse(
        request, "promos.html",
        {
            "active": "promos", "admin": request.session.get("admin"),
            "promos": [_promo_view(p) for p in promos],
            "ok": ok, "error": error,
        },
    )


@router.get("/promos")
async def promos_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


@router.post("/promos/create")
async def promo_create(request: Request):
    current_admin(request)
    pool = get_pool()
    form = await request.form()

    code = promo_service.normalize_code(form.get("code"))
    if not code or " " in code or len(code) > 32:
        return await _overview(request, error="Код пустой или некорректный (без пробелов, до 32 символов).")
    if await repo.get_promo_by_code(pool, code) is not None:
        return await _overview(request, error=f"Промокод «{code}» уже существует.")

    kind = (form.get("kind") or "").strip()
    if kind not in (promo_service.KIND_PERCENT, promo_service.KIND_FIXED):
        return await _overview(request, error="Выберите тип промокода.")

    try:
        value = Decimal((form.get("value") or "").replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return await _overview(request, error="Значение — это число.")
    if kind == promo_service.KIND_PERCENT:
        if not (0 < value < 100):
            return await _overview(request, error="Процент скидки должен быть от 1 до 99.")
    elif value <= 0:
        return await _overview(request, error="Спец-цена должна быть больше нуля.")

    limit_raw = (form.get("limit") or "0").strip()
    if not limit_raw.isdigit():
        return await _overview(request, error="Лимит активаций — целое число (0 — без лимита).")
    limit = int(limit_raw)

    days_raw = (form.get("expiry_days") or "0").strip()
    if not days_raw.isdigit():
        return await _overview(request, error="Срок действия — целое число дней (0 — бессрочно).")
    days = int(days_raw)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None
    )

    fixes = form.get("fixes_price") is not None

    promo_id = await repo.create_promo(
        pool,
        code=code,
        kind=kind,
        value=value,
        max_activations=None if limit == 0 else limit,
        expires_at=expires_at,
        fixes_price=fixes,
    )
    if promo_id is None:
        return await _overview(request, error=f"Промокод «{code}» уже существует.")
    logger.info(
        "Админка: создан промокод #{} {} ({}={}, лимит={}, фикс={})",
        promo_id, code, kind, value, limit, fixes,
    )
    return RedirectResponse(f"/promos?ok=Промокод «{code}» создан.", status_code=303)


@router.post("/promos/{promo_id}/toggle")
async def promo_toggle(request: Request, promo_id: int):
    current_admin(request)
    pool = get_pool()
    p = await repo.get_promo(pool, promo_id)
    if p is not None:
        await repo.set_promo_active(pool, promo_id, not p["is_active"])
        logger.info("Админка: промокод #{} active={}", promo_id, not p["is_active"])
    return RedirectResponse("/promos?ok=Сохранено.", status_code=303)


@router.post("/promos/{promo_id}/delete")
async def promo_delete(request: Request, promo_id: int):
    current_admin(request)
    pool = get_pool()
    if await repo.delete_promo(pool, promo_id):
        logger.info("Админка: удалён промокод #{}", promo_id)
    return RedirectResponse("/promos?ok=Промокод удалён.", status_code=303)
