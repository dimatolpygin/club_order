"""Промокоды: нормализация кода, валидация и расчёт спец-цены (этап 7).

Логика вынесена из хендлеров отдельными функциями без БД/сети — её удобно
тестировать. Валидация различает статусы: ok / not_found / expired / exhausted /
already_used. Расчёт цены поддерживает два типа кода:
  · fixed_price — спец-ставка в ₽/мес (сумма = ставка × число периодов);
  · percent     — скидка % от обычной цены (и ставки, и суммы периода).
Если код фиксирует цену (fixes_price) — за подпиской сохраняется спец-ставка,
иначе фиксируется обычная ставка ступени (промо разово удешевляет покупку).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# Статусы валидации.
VALID = "ok"
NOT_FOUND = "not_found"
EXPIRED = "expired"
EXHAUSTED = "exhausted"
ALREADY_USED = "already_used"

# Типы кодов.
KIND_FIXED = "fixed_price"
KIND_PERCENT = "percent"


def normalize_code(raw: str | None) -> str:
    """Код к каноничному виду: без пробелов по краям, верхний регистр."""
    return (raw or "").strip().upper()


def validate(promo, *, now: datetime, already_used: bool) -> str:
    """Статус промокода. promo — запись из БД или None."""
    if promo is None:
        return NOT_FOUND
    if not promo["is_active"]:
        return EXPIRED  # деактивированный код больше не действует
    if promo["expires_at"] is not None and promo["expires_at"] <= now:
        return EXPIRED
    if (
        promo["max_activations"] is not None
        and promo["used_count"] >= promo["max_activations"]
    ):
        return EXHAUSTED
    if already_used:
        return ALREADY_USED
    return VALID


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_pricing(
    promo, *, tier_monthly: Decimal, period_price: Decimal, months: int
) -> dict:
    """Спец-цена по промокоду.

    tier_monthly — обычная ставка ступени; period_price — обычная цена выбранного
    периода (из матрицы tier_prices). Возвращает:
      special_monthly — спец-ставка ₽/мес (для показа «спец-цена»);
      amount          — итоговая сумма к оплате за период;
      fixed_price     — что фиксируется за подпиской (для продлений).
    """
    value: Decimal = promo["value"]
    if promo["kind"] == KIND_PERCENT:
        factor = (Decimal(100) - value) / Decimal(100)
        special_monthly = _money(tier_monthly * factor)
        amount = _money(period_price * factor)
    else:  # fixed_price
        special_monthly = _money(value)
        amount = _money(special_monthly * months)
    fixed_price = special_monthly if promo["fixes_price"] else _money(tier_monthly)
    return {
        "special_monthly": special_monthly,
        "amount": amount,
        "fixed_price": fixed_price,
    }
