"""Логика цены пакета консультаций: скидки + промокод + бонусы (этап 47).

Проверяет чистые кусочки, на которых стоит расчёт `service_sales.compute_service_pricing`
(сам он ходит в БД и здесь не запускается):
  · скидки подписчика / промокода / новичка НЕ суммируются — берётся максимальная
    (`events.best_ticket_price`, тот же движок, что у билетов);
  · процент-промокод участвует наравне со скидкой подписчика (у услуг — впервые);
  · бонусы добивают цену уже со скидкой, но не более 50% (`events.bonus_cap`);
  · рефералка для консультаций — мгновенная категория (бонус пригласившему сразу).
Запуск: python -m tests.test_consult_sales
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
    base = Decimal("10000")  # цена пакета «4 консультации» (условно)

    # ── Промокод −20% выгоднее скидки участника −10% → берём промокод ────────
    price, applied = ev.best_ticket_price(base, subscriber_pct=10, promo_pct=20)
    check("промокод −20% выгоднее −10% → 8000", price, Decimal("8000.00"))
    check("применён промокод", applied, "promo")

    # ── Скидка участника −30% выгоднее промокода −20% → берём подписку ───────
    price2, applied2 = ev.best_ticket_price(base, subscriber_pct=30, promo_pct=20)
    check("подписка −30% выгоднее −20% → 7000", price2, Decimal("7000.00"))
    check("применена скидка участника", applied2, "subscriber")

    # ── Новичок −500 ₽ vs промокод −20% (8000) → промокод выгоднее ──────────
    price3, applied3 = ev.best_ticket_price(base, promo_pct=20, referral_amount=500)
    check("промокод −20% (8000) выгоднее −500 ₽", price3, Decimal("8000.00"))
    check("применён промокод, не рефералка", applied3, "promo")

    # ── Бонусы добивают цену со скидкой, но не более 50% ────────────────────
    # Цена со скидкой 8000 → потолок бонусов 4000; кошелёк 10000 → списываем 4000.
    cap = ev.bonus_cap(Decimal("8000.00"), 10000)
    check("бонусы: потолок 50% от 8000 = 4000", cap, 4000)
    check("итого к оплате 8000 − 4000 = 4000", Decimal("8000.00") - Decimal(cap), Decimal("4000.00"))
    # Кошелёк меньше потолка — списываем весь кошелёк.
    check("кошелёк 1500 < потолка → 1500", ev.bonus_cap(Decimal("8000.00"), 1500), 1500)

    # ── Без скидок — полная цена ────────────────────────────────────────────
    price0, applied0 = ev.best_ticket_price(base)
    check("без скидок → 10000", price0, Decimal("10000"))
    check("скидок нет", applied0, "none")

    # ── Рефералка консультаций — мгновенная (нет даты события) ──────────────
    check("консультации — категория 'consult'", ref_rules.CATEGORY_CONSULT, "consult")
    check("консультации начисляются сразу", ref_rules.is_instant(ref_rules.CATEGORY_CONSULT), True)
    check("подпись категории", ref_rules.category_label("consult"), "Консультации")

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
