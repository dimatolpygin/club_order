"""Приоритет фикс-промо-цены над скидкой продления (этап 44).

Проверяет tariffs.renewal_monthly_for без БД: подписка с закреплённой промо-ценой
(price_locked=True) продлевается по своей fixed_price, обычная — по текущей цене
продления (renewal_rate из bot_settings); если цена продления не задана (0) —
падаем на fixed_price подписки.
Запуск: python -m tests.test_renewal_price_lock
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from src.services import tariffs


class FakePool:
    """Отдаёт только заданные ключи bot_settings (как в test_subscription_prices)."""

    def __init__(self, settings: dict[str, str]):
        self._settings = settings

    async def fetch(self, _query: str, keys):
        return [
            {"key": k, "value": self._settings[k]}
            for k in keys
            if k in self._settings
        ]


def sub(*, fixed_price: str, price_locked: bool) -> dict:
    return {"fixed_price": Decimal(fixed_price), "price_locked": price_locked}


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    pool = FakePool({
        "subscription_entry_price": "5000",
        "subscription_renewal_price": "4000",
    })

    # Обычная подписка → по текущей цене продления (не по своей ставке).
    normal = sub(fixed_price="5000", price_locked=False)
    check(
        "обычная → цена продления",
        asyncio.run(tariffs.renewal_monthly_for(pool, normal)),
        Decimal("4000"),
    )

    # Залоченная промо-ценой → по своей fixed_price, скидка продления не действует.
    locked = sub(fixed_price="500", price_locked=True)
    check(
        "фикс-промо → своя цена (приоритет промокода)",
        asyncio.run(tariffs.renewal_monthly_for(pool, locked)),
        Decimal("500"),
    )
    # И даже если цена продления (4000) ВЫШЕ промо-цены — платим по промокоду.
    check(
        "фикс-промо дешевле продления → всё равно по промо",
        asyncio.run(tariffs.renewal_monthly_for(pool, locked)) < Decimal("4000"),
        True,
    )

    # Цена продления не задана (0) у обычной подписки → падаем на её ставку.
    no_renewal = FakePool({"subscription_entry_price": "5000"})
    check(
        "нет цены продления → ставка подписки",
        asyncio.run(tariffs.renewal_monthly_for(no_renewal, normal)),
        Decimal("5000"),
    )

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
