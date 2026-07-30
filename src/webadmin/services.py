"""Раздел админки «Йога» (этап 46): цены форматов занятий.

Продукты услуги (service_products, category='yoga') редактируются здесь: цена за
занятие, скидка подписчику, вкл/выкл. Набор форматов (индивидуальное/групповое)
задан миграцией-сидом — добавление/удаление не требуется (решение раунда 4).
Контакт менеджера-редиректа — общий для услуг, живёт в «Настройках». Описание
раздела (текст сверху) правится в «Экранах бота» (ключ 'yoga'). Правки применяются
в боте сразу. Тот же движок переиспользуют консультации (этап 47) — другая категория.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..utils import fmt_price
from .deps import current_admin, templates

router = APIRouter()

CATEGORY = "yoga"


def _parse_int(raw: str | None, *, field: str) -> int:
    """Целое ≥ 0 из строки формы. Терпит разделитель тысяч (пробел) и запятую."""
    raw = "".join(ch for ch in (raw or "") if not ch.isspace()).replace(",", ".")
    if raw == "":
        raise ValueError(field)
    try:
        val = Decimal(raw)
    except InvalidOperation:
        raise ValueError(field)
    if val < 0:
        raise ValueError(field)
    return int(val)


async def _overview(request: Request, *, ok: str | None = None, error: str | None = None):
    pool = get_pool()
    products = await repo.list_service_products(pool, CATEGORY)
    rows = [
        {
            "id": p["id"], "title": p["title"], "code": p["code"],
            "price": fmt_price(p["price"]),
            "discount": p["subscriber_discount_percent"],
            "is_active": p["is_active"],
        }
        for p in products
    ]
    return templates.TemplateResponse(
        request, "yoga.html",
        {
            "active": "yoga", "admin": request.session.get("admin"),
            "products": rows, "ok": ok, "error": error,
        },
    )


@router.get("/yoga")
async def yoga_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


@router.post("/yoga/products/{product_id}")
async def yoga_product_save(request: Request, product_id: int):
    current_admin(request)
    pool = get_pool()
    product = await repo.get_service_product(pool, product_id)
    if product is None or product["category"] != CATEGORY:
        return RedirectResponse("/yoga?error=Формат не найден.", status_code=303)
    form = await request.form()
    try:
        price = _parse_int(form.get("price"), field="цена")
        discount = _parse_int(form.get("discount"), field="скидка")
    except ValueError:
        return await _overview(
            request, error="Цена и скидка — целые числа (0 или больше)."
        )
    if discount > 100:
        return await _overview(request, error="Скидка подписчику — от 0 до 100%.")
    is_active = form.get("is_active") is not None
    await repo.update_service_product(
        pool, product_id, price=price,
        subscriber_discount_percent=discount, is_active=is_active,
    )
    logger.info(
        "Админка: йога-формат #{} цена={} скидка={}% активен={}",
        product_id, price, discount, is_active,
    )
    return RedirectResponse("/yoga?ok=Сохранено.", status_code=303)
