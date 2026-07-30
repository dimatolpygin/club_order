"""Разделы админки «Йога» и «Консультации» (этапы 46/47): цены услуг «по количеству».

Продукты услуг (service_products) редактируются здесь: цена, скидка подписчику,
вкл/выкл. Набор продуктов задан миграциями-сидами (йога: индивидуальное/групповое;
консультации: пакеты 1/4/8/12) — добавление/удаление не требуется (решение раунда 4).
Контакт менеджера-редиректа — общий для услуг, живёт в «Настройках». Описание
раздела (текст сверху) правится в «Экранах бота» (ключи 'yoga'/'consult'). Правки
применяются в боте сразу. Оба раздела делят один движок продаж (services.service_sales)
и различаются лишь категорией продукта и подписями.
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

# Метаданные раздела: (категория продукта, шаблон, метка nav, человекочитаемое имя).
_SECTIONS = {
    "yoga": ("yoga", "yoga.html", "Формат"),
    "consult": ("consult", "consult.html", "Пакет"),
}


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


async def _overview(
    request: Request, category: str, *, ok: str | None = None, error: str | None = None
):
    _cat, template, _label = _SECTIONS[category]
    pool = get_pool()
    products = await repo.list_service_products(pool, category)
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
        request, template,
        {
            "active": category, "admin": request.session.get("admin"),
            "products": rows, "ok": ok, "error": error,
        },
    )


async def _save_product(request: Request, category: str, product_id: int):
    """Общая обработка формы правки продукта услуги (цена/скидка/вкл-выкл)."""
    pool = get_pool()
    product = await repo.get_service_product(pool, product_id)
    if product is None or product["category"] != category:
        return RedirectResponse(f"/{category}?error=Продукт не найден.", status_code=303)
    form = await request.form()
    try:
        price = _parse_int(form.get("price"), field="цена")
        discount = _parse_int(form.get("discount"), field="скидка")
    except ValueError:
        return await _overview(
            request, category, error="Цена и скидка — целые числа (0 или больше)."
        )
    if discount > 100:
        return await _overview(request, category, error="Скидка подписчику — от 0 до 100%.")
    is_active = form.get("is_active") is not None
    await repo.update_service_product(
        pool, product_id, price=price,
        subscriber_discount_percent=discount, is_active=is_active,
    )
    logger.info(
        "Админка: услуга «{}» #{} цена={} скидка={}% активен={}",
        category, product_id, price, discount, is_active,
    )
    return RedirectResponse(f"/{category}?ok=Сохранено.", status_code=303)


# ── Йога ─────────────────────────────────────────────────────────────────────
@router.get("/yoga")
async def yoga_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, "yoga", ok=ok, error=error)


@router.post("/yoga/products/{product_id}")
async def yoga_product_save(request: Request, product_id: int):
    current_admin(request)
    return await _save_product(request, "yoga", product_id)


# ── Консультации (этап 47) ───────────────────────────────────────────────────
@router.get("/consult")
async def consult_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, "consult", ok=ok, error=error)


@router.post("/consult/products/{product_id}")
async def consult_product_save(request: Request, product_id: int):
    current_admin(request)
    return await _save_product(request, "consult", product_id)
