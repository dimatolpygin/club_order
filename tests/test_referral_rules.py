"""Изолированный smoke-тест правил реф-программы по категориям (этап 40).

Проверяет services.referral_rules без БД: расчёт скидки новичку и бонуса
пригласившему для типов «сумма» и «процент», границы (ноль, отрицательные,
скидка больше цены), момент начисления по категориям и форматирование величины.
Запуск: python -m tests.test_referral_rules
"""
from __future__ import annotations

from decimal import Decimal

from src.services import referral_rules as rr


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got!r} expected={expected!r}")
    assert got == expected, name


def rule(dk="fixed", dv=0, bk="fixed", bv=0) -> dict:
    return {
        "discount_kind": dk, "discount_value": Decimal(str(dv)),
        "bonus_kind": bk, "bonus_value": Decimal(str(bv)),
    }


def main() -> None:
    # ── Скидка новичку: фиксированная сумма ──────────────────────────────────
    check("скидка fixed 500 от 3000", rr.discount_for(rule(dv=500), 3000), 500)
    check("скидка fixed 0 → 0", rr.discount_for(rule(dv=0), 3000), 0)
    check("скидка fixed больше цены → цена (в минус не уходим)",
          rr.discount_for(rule(dv=5000), 3000), 3000)
    check("нет правила → 0", rr.discount_for(None, 3000), 0)

    # ── Скидка новичку: процент ──────────────────────────────────────────────
    check("скидка 10% от 3000", rr.discount_for(rule(dk="percent", dv=10), 3000), 300)
    check("скидка 15% от 999 → вниз до рубля (149.85)",
          rr.discount_for(rule(dk="percent", dv=15), 999), 149)
    check("скидка 100% от 2000 → вся цена",
          rr.discount_for(rule(dk="percent", dv=100), 2000), 2000)
    check("скидка процентом от нулевой цены → 0",
          rr.discount_for(rule(dk="percent", dv=10), 0), 0)

    # ── Бонус пригласившему ──────────────────────────────────────────────────
    check("бонус fixed 1000", rr.bonus_for(rule(bv=1000), 3000), 1000)
    check("бонус 5% от 3000", rr.bonus_for(rule(bk="percent", bv=5), 3000), 150)
    check("бонус 7% от 1000 → вниз (70)", rr.bonus_for(rule(bk="percent", bv=7), 1000), 70)
    check("бонус 3% от 999 → вниз (29.97 → 29)",
          rr.bonus_for(rule(bk="percent", bv=3), 999), 29)
    # Фиксированный бонус НЕ ограничен суммой покупки (решение заказчика).
    check("бонус fixed 1000 при покупке 500 — не режем",
          rr.bonus_for(rule(bv=1000), 500), 1000)
    check("бонус 0 → 0", rr.bonus_for(rule(bv=0), 3000), 0)
    check("нет правила → бонус 0", rr.bonus_for(None, 3000), 0)

    # ── Момент начисления по категориям ──────────────────────────────────────
    check("баня — не сразу (ждёт даты события)", rr.is_instant(rr.CATEGORY_BANYA), False)
    check("ретрит — не сразу", rr.is_instant(rr.CATEGORY_RETREAT), False)
    check("подписка — сразу", rr.is_instant(rr.CATEGORY_SUBSCRIPTION), True)
    check("йога — сразу", rr.is_instant(rr.CATEGORY_YOGA), True)
    check("консультации — сразу", rr.is_instant(rr.CATEGORY_CONSULT), True)

    # ── Категория по виду события ────────────────────────────────────────────
    check("kind banya → категория banya",
          rr.category_for_event_kind("banya"), rr.CATEGORY_BANYA)
    check("kind retreat → категория retreat",
          rr.category_for_event_kind("retreat"), rr.CATEGORY_RETREAT)

    # ── Нормализация типа из формы админки ───────────────────────────────────
    check("тип percent проходит", rr.normalize_kind("percent"), rr.KIND_PERCENT)
    check("мусор → fixed", rr.normalize_kind("xxx"), rr.KIND_FIXED)
    check("None → fixed", rr.normalize_kind(None), rr.KIND_FIXED)

    # ── Показ величины на экране «Пригласить друга» ──────────────────────────
    check("показ fixed", rr.discount_phrase(rule(dv=500)), "500 ₽")
    check("показ percent", rr.discount_phrase(rule(dk="percent", dv=10)), "10%")
    check("показ без правила — дефолт", rr.discount_phrase(None), "500 ₽")

    # Все пять категорий на месте и уникальны.
    check("категорий пять", len(rr.CATEGORIES), 5)
    check("категории уникальны", len(set(rr.CATEGORIES)), 5)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
