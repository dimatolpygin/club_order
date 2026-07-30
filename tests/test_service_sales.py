"""Логика цены услуги «по количеству»: йога (этап 46).

Проверяет чистые кусочки, на которых стоит расчёт `service_sales.compute_service_pricing`
(сам он ходит в БД и здесь не запускается):
  · сумма = цена продукта × количество;
  · скидки подписчика и новичка НЕ суммируются — берётся максимальная
    (`events.best_ticket_price`, тот же движок, что у билетов);
  · рефералка для йоги — мгновенная категория (бонус пригласившему сразу).
Запуск: python -m tests.test_service_sales
"""
from __future__ import annotations

from decimal import Decimal

from src.services import events as ev
from src.services import referral_rules as ref_rules


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # ── Сумма = цена × количество ───────────────────────────────────────────
    unit_price, quantity = 1000, 3
    base = Decimal(str(unit_price)) * quantity
    check("1000 ₽ × 3 = 3000", base, Decimal("3000"))

    # ── Скидки не суммируются — берётся максимальная (меньшая цена) ──────────
    price, applied = ev.best_ticket_price(base, subscriber_pct=10, referral_amount=0)
    check("подписчик −10% от 3000 → 2700", price, Decimal("2700.00"))
    check("применена скидка подписчика", applied, "subscriber")

    # Новичок −500 ₽ выгоднее подписки −10% (2500 < 2700) → берём рефералку.
    price2, applied2 = ev.best_ticket_price(base, subscriber_pct=10, referral_amount=500)
    check("новичок −500 ₽ выгоднее → 2500", price2, Decimal("2500"))
    check("применена скидка новичка", applied2, "referral")

    # Без скидок — полная цена.
    price0, applied0 = ev.best_ticket_price(base)
    check("без скидок → 3000", price0, Decimal("3000"))
    check("скидок нет", applied0, "none")

    # ── Рефералка йоги — мгновенная (нет даты события) ──────────────────────
    check("йога — категория 'yoga'", ref_rules.CATEGORY_YOGA, "yoga")
    check("йога начисляется сразу", ref_rules.is_instant(ref_rules.CATEGORY_YOGA), True)
    check("подпись категории", ref_rules.category_label("yoga"), "Йога")

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
