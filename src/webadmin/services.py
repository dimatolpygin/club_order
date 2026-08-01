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

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..utils import fmt_price
from .deps import current_admin, templates

router = APIRouter()

# Метаданные раздела: (шаблон, метка формата/пакета, слово для итогов «продано N …»).
_SECTIONS = {
    "yoga": ("yoga.html", "Формат", "занятий"),
    "consult": ("consult.html", "Пакет", "пакетов"),
}
# Продаж на странице журнала (этап 51) — как в «Билетах».
PER_PAGE = 50


def _parse_date(raw: str | None) -> date | None:
    """Парсит дату из <input type=date> (YYYY-MM-DD); мусор → None."""
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


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
    template, item_label, item_word = _SECTIONS[category]
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

    # Журнал продаж услуги (этап 51): фильтры из query-строки, пагинация, итоги.
    qp = request.query_params
    search = (qp.get("q") or "").strip()
    product_code = (qp.get("product") or "").strip()
    date_from = _parse_date(qp.get("from"))
    date_to = _parse_date(qp.get("to"))
    raw_p = qp.get("page", "1")
    page = int(raw_p) if raw_p.strip().isdigit() else 1
    total = await repo.count_service_sales(
        pool, category, search=search, product_code=product_code,
        date_from=date_from, date_to=date_to,
    )
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(max(1, page), pages)
    sale_rows = await repo.list_service_sales(
        pool, category, search=search, product_code=product_code,
        date_from=date_from, date_to=date_to,
        limit=PER_PAGE, offset=(page - 1) * PER_PAGE,
    )
    totals = await repo.service_sales_totals(
        pool, category, search=search, product_code=product_code,
        date_from=date_from, date_to=date_to,
    )
    sales = [
        {
            "id": r["id"], "created_at": r["created_at"], "tg_id": r["tg_id"],
            "name": (r["first_name"] or "").strip() or "—",
            "username": r["username"], "title": r["title"],
            "quantity": r["quantity"], "amount": fmt_price(r["amount"]),
        }
        for r in sale_rows
    ]
    totals_view = {
        "quantity": totals["quantity"], "buyers": totals["buyers"],
        "amount": fmt_price(totals["amount"]),
    }

    return templates.TemplateResponse(
        request, template,
        {
            "active": category, "admin": request.session.get("admin"),
            "products": rows, "ok": ok, "error": error,
            # Журнал продаж (этап 51) — общий партиал _service_sales.html.
            "category": category, "item_label": item_label, "item_word": item_word,
            "sales": sales, "totals": totals_view,
            "search": search, "product_code": product_code,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "page": page, "pages": pages, "total": total, "per_page": PER_PAGE,
        },
    )


async def _sales_csv(request: Request, category: str) -> Response:
    """Выгрузка журнала продаж услуги в CSV по текущим фильтрам (этап 51).

    UTF-8 с BOM — кириллица корректно открывается в Excel. Колонки: № · Дата покупки ·
    Покупатель · @username · Telegram ID · Формат/Пакет · Количество · Сумма.
    """
    pool = get_pool()
    _template, item_label, _word = _SECTIONS[category]
    qp = request.query_params
    search = (qp.get("q") or "").strip()
    product_code = (qp.get("product") or "").strip()
    date_from = _parse_date(qp.get("from"))
    date_to = _parse_date(qp.get("to"))
    rows = await repo.list_service_sales(
        pool, category, search=search, product_code=product_code,
        date_from=date_from, date_to=date_to,
    )
    buf = io.StringIO()
    buf.write("﻿")  # BOM для Excel
    w = csv.writer(buf, delimiter=";")
    w.writerow(["№", "Дата покупки", "Покупатель", "@username", "Telegram ID",
                item_label, "Количество", "Сумма, ₽"])
    for n, r in enumerate(rows, start=1):
        name = (r["first_name"] or "").strip() or "—"
        username = f"@{r['username']}" if r["username"] else "—"
        dt = r["created_at"].strftime("%d.%m.%Y %H:%M") if r["created_at"] else "—"
        w.writerow([n, dt, name, username, r["tg_id"], r["title"],
                    r["quantity"], fmt_price(r["amount"])])
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{category}_sales.csv"'},
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


@router.get("/yoga/sales.csv")
async def yoga_sales_csv(request: Request):
    current_admin(request)
    return await _sales_csv(request, "yoga")


@router.post("/yoga/products/{product_id}")
async def yoga_product_save(request: Request, product_id: int):
    current_admin(request)
    return await _save_product(request, "yoga", product_id)


# ── Консультации (этап 47) ───────────────────────────────────────────────────
@router.get("/consult")
async def consult_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, "consult", ok=ok, error=error)


@router.get("/consult/sales.csv")
async def consult_sales_csv(request: Request):
    current_admin(request)
    return await _sales_csv(request, "consult")


@router.post("/consult/products/{product_id}")
async def consult_product_save(request: Request, product_id: int):
    current_admin(request)
    return await _save_product(request, "consult", product_id)
