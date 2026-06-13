"""Изолированный smoke-тест логики промокодов (этап 7).

Проверяет чистые функции services.promo без БД: статусы валидации
(не найден/истёк/исчерпан/уже использован/ок) и расчёт спец-цены для обоих типов
(спец-ставка и процент), включая фиксацию цены и округление.
Запуск: python -m tests.test_promo
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services import promo as p

NOW = datetime(2026, 6, 13, tzinfo=timezone.utc)


def _promo(**over) -> dict:
    base = {
        "kind": p.KIND_FIXED,
        "value": Decimal("555"),
        "max_activations": None,
        "used_count": 0,
        "expires_at": None,
        "fixes_price": False,
        "is_active": True,
    }
    base.update(over)
    return base


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # ── Валидация ─────────────────────────────────────────────────────────────
    check("None → not_found",
          p.validate(None, now=NOW, already_used=False), p.NOT_FOUND)
    check("выключен → expired",
          p.validate(_promo(is_active=False), now=NOW, already_used=False), p.EXPIRED)
    check("просрочен → expired",
          p.validate(_promo(expires_at=NOW - timedelta(days=1)), now=NOW, already_used=False),
          p.EXPIRED)
    check("ещё действует → ok",
          p.validate(_promo(expires_at=NOW + timedelta(days=1)), now=NOW, already_used=False),
          p.VALID)
    check("лимит исчерпан → exhausted",
          p.validate(_promo(max_activations=5, used_count=5), now=NOW, already_used=False),
          p.EXHAUSTED)
    check("лимит ещё есть → ok",
          p.validate(_promo(max_activations=5, used_count=4), now=NOW, already_used=False),
          p.VALID)
    check("уже использован → already_used",
          p.validate(_promo(), now=NOW, already_used=True), p.ALREADY_USED)
    check("чистый валидный → ok",
          p.validate(_promo(), now=NOW, already_used=False), p.VALID)

    # ── Расчёт: спец-ставка ───────────────────────────────────────────────────
    r = p.compute_pricing(
        _promo(value=Decimal("555"), fixes_price=True),
        tier_monthly=Decimal("1111"), period_price=Decimal("3333"), months=3,
    )
    check("fixed: special", r["special_monthly"], Decimal("555.00"))
    check("fixed: amount = 555×3", r["amount"], Decimal("1665.00"))
    check("fixed+фикс: fixed_price = спец", r["fixed_price"], Decimal("555.00"))

    r = p.compute_pricing(
        _promo(value=Decimal("555"), fixes_price=False),
        tier_monthly=Decimal("1111"), period_price=Decimal("3333"), months=3,
    )
    check("fixed без фикс: fixed_price = ставка ступени", r["fixed_price"], Decimal("1111.00"))

    # ── Расчёт: процент ───────────────────────────────────────────────────────
    r = p.compute_pricing(
        _promo(kind=p.KIND_PERCENT, value=Decimal("20"), fixes_price=True),
        tier_monthly=Decimal("1000"), period_price=Decimal("3000"), months=3,
    )
    check("percent: special = 1000×0.8", r["special_monthly"], Decimal("800.00"))
    check("percent: amount = 3000×0.8", r["amount"], Decimal("2400.00"))
    check("percent+фикс: fixed = спец", r["fixed_price"], Decimal("800.00"))

    r = p.compute_pricing(
        _promo(kind=p.KIND_PERCENT, value=Decimal("33"), fixes_price=False),
        tier_monthly=Decimal("1000"), period_price=Decimal("3000"), months=3,
    )
    check("percent 33%: special округл.", r["special_monthly"], Decimal("670.00"))
    check("percent 33%: amount округл.", r["amount"], Decimal("2010.00"))
    check("percent без фикс: fixed = ставка", r["fixed_price"], Decimal("1000.00"))

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
