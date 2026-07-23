"""Раздел админки «Реферальная программа» (этап 17; категории — этап 40).

Настройка правил ПО КАТЕГОРИЯМ покупок (баня, ретрит, подписка, йога,
консультации): скидка новичку и бонус пригласившему, каждое — суммой в рублях
или процентом от суммы покупки. Плюс просмотр цепочек приглашений и ручное
начисление/списание бонусов. Данные читаем напрямую из общего слоя бота (repo).
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..services import referral_rules as ref_rules
from .deps import current_admin, templates

router = APIRouter()

# Человекочитаемые статусы реф-связи.
STATUS_LABELS = {
    "pending": "Перешёл (ждёт первой покупки)",
    "qualified": "Купил (бонус ждёт начисления)",
    "accrued": "Бонус начислен",
    "void": "Аннулирован",
}


async def _rule_rows(pool) -> list[dict]:
    """Правила всех категорий для формы (недостающие строки — дефолтами сервиса)."""
    stored = await repo.get_referral_rules(pool)
    rows: list[dict] = []
    for category in ref_rules.CATEGORIES:
        r = stored.get(category)
        rows.append({
            "category": category,
            "label": ref_rules.category_label(category),
            "discount_kind": r["discount_kind"] if r else ref_rules.KIND_FIXED,
            "discount_value": int(r["discount_value"]) if r else ref_rules.DEFAULT_DISCOUNT,
            "bonus_kind": r["bonus_kind"] if r else ref_rules.KIND_FIXED,
            "bonus_value": int(r["bonus_value"]) if r else ref_rules.DEFAULT_BONUS,
        })
    return rows


async def _render(request: Request, *, error: str | None = None, ok: str | None = None,
                  status: int = 200):
    pool = get_pool()
    chains = await repo.get_referral_chains(pool)
    return templates.TemplateResponse(
        request, "referral.html",
        {
            "active": "referral", "admin": request.session.get("admin"),
            "rules": await _rule_rows(pool),
            "kinds": [(k, ref_rules.KIND_LABELS[k]) for k in ref_rules.KINDS],
            "chains": chains, "status_labels": STATUS_LABELS,
            "error": error, "ok": ok,
        },
        status_code=status,
    )


@router.get("/referral")
async def referral_page(request: Request):
    current_admin(request)
    return await _render(request)


@router.post("/referral/settings")
async def referral_settings(request: Request):
    """Сохраняет правила всех категорий одной формой (этап 40)."""
    current_admin(request)
    form = await request.form()
    parsed: list[dict] = []
    for category in ref_rules.CATEGORIES:
        label = ref_rules.category_label(category)
        try:
            dv = int((form.get(f"discount_value_{category}") or "0").strip() or 0)
            bv = int((form.get(f"bonus_value_{category}") or "0").strip() or 0)
        except ValueError:
            return await _render(
                request, error=f"«{label}»: величины должны быть целыми числами.", status=400
            )
        if dv < 0 or bv < 0:
            return await _render(
                request, error=f"«{label}»: величины не могут быть отрицательными.", status=400
            )
        dk = ref_rules.normalize_kind(form.get(f"discount_kind_{category}"))
        bk = ref_rules.normalize_kind(form.get(f"bonus_kind_{category}"))
        if (dk == ref_rules.KIND_PERCENT and dv > 100) or (
            bk == ref_rules.KIND_PERCENT and bv > 100
        ):
            return await _render(
                request, error=f"«{label}»: процент не может быть больше 100.", status=400
            )
        parsed.append({
            "category": category, "discount_kind": dk, "discount_value": dv,
            "bonus_kind": bk, "bonus_value": bv,
        })

    pool = get_pool()
    for p in parsed:
        await repo.upsert_referral_rule(
            pool, p["category"],
            discount_kind=p["discount_kind"], discount_value=p["discount_value"],
            bonus_kind=p["bonus_kind"], bonus_value=p["bonus_value"],
        )
    logger.info("Админка: правила рефералки обновлены ({} категорий)", len(parsed))
    return await _render(request, ok="Суммы по категориям сохранены.")


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
