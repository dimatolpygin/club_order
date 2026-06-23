"""Раздел админки «Реферальная программа» (этап 17).

Настройка сумм (скидка новичку / бонус пригласившему), просмотр цепочек
приглашений и ручное начисление/списание бонусов. Данные читаем напрямую из
общего слоя бота (repo) и app_settings — отдельный repo раздела не нужен.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..services import app_settings
from .deps import current_admin, templates

router = APIRouter()

# Человекочитаемые статусы реф-связи.
STATUS_LABELS = {
    "pending": "Перешёл (ждёт первой покупки)",
    "qualified": "Купил баню (бонус после события)",
    "accrued": "Бонус начислен",
    "void": "Аннулирован",
}


async def _render(request: Request, *, error: str | None = None, ok: str | None = None,
                  status: int = 200):
    pool = get_pool()
    sums = await app_settings.referral_sums(pool)
    chains = await repo.get_referral_chains(pool)
    return templates.TemplateResponse(
        request, "referral.html",
        {
            "active": "referral", "admin": request.session.get("admin"),
            "sums": sums, "chains": chains, "status_labels": STATUS_LABELS,
            "error": error, "ok": ok,
        },
        status_code=status,
    )


@router.get("/referral")
async def referral_page(request: Request):
    current_admin(request)
    return await _render(request)


@router.post("/referral/settings")
async def referral_settings(
    request: Request,
    newbie_discount: str = Form(...),
    referrer_bonus: str = Form(...),
):
    current_admin(request)
    try:
        d = int((newbie_discount or "").strip())
        b = int((referrer_bonus or "").strip())
    except ValueError:
        return await _render(request, error="Суммы должны быть целыми числами.", status=400)
    if d < 0 or b < 0:
        return await _render(request, error="Суммы не могут быть отрицательными.", status=400)
    pool = get_pool()
    await app_settings.set_referral_sum(pool, newbie_discount=d, referrer_bonus=b)
    logger.info("Админка: суммы рефералки обновлены — скидка {} ₽, бонус {} ₽", d, b)
    return await _render(request, ok="Суммы сохранены.")


@router.post("/referral/bonus")
async def referral_bonus(
    request: Request,
    tg_id: str = Form(...),
    amount: str = Form(...),
    note: str = Form(""),
):
    current_admin(request)
    try:
        uid = int((tg_id or "").strip())
        delta = int((amount or "").strip())
    except ValueError:
        return await _render(request, error="Telegram ID и сумма — целые числа.", status=400)
    if delta == 0:
        return await _render(request, error="Сумма не может быть нулевой.", status=400)
    pool = get_pool()
    balance = await repo.bonus_balance(pool, uid)
    if delta < 0 and balance + delta < 0:
        return await _render(
            request,
            error=f"Нельзя списать {-delta} ₽: на балансе только {balance} ₽.",
            status=400,
        )
    new_balance = await repo.add_bonus_manual(
        pool, tg_id=uid, amount=delta, note=(note or "").strip() or None
    )
    sign = "начислено" if delta > 0 else "списано"
    logger.info("Админка: бонусы вручную {} {} ₽ для id={} (баланс {})",
                sign, abs(delta), uid, new_balance)
    return await _render(
        request,
        ok=f"Готово: {sign} {abs(delta)} ₽ для id={uid}. Новый баланс: {new_balance} ₽.",
    )
