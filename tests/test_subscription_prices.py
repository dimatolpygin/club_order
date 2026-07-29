"""Smoke-тест тарифа вход/продление (этап 43) — без ступеней по местам.

Проверяет две цены (вход/продление) из bot_settings и расчёт цены за срок без БД:
подставляем фейковый пул, отдающий заранее заданные значения bot_settings.
Запуск: python -m tests.test_subscription_prices
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from src.services import app_settings
from src.services import tariffs


class FakePool:
    """Мини-заглушка пула: отдаёт только заданные ключи bot_settings."""

    def __init__(self, settings: dict[str, str]):
        self._settings = settings

    async def fetch(self, _query: str, keys):
        return [
            {"key": k, "value": self._settings[k]}
            for k in keys
            if k in self._settings
        ]


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # ── Парсинг цены из строки bot_settings ──────────────────────────────────
    check("_to_price пусто → 0", app_settings._to_price(None), Decimal(0))
    check("_to_price '' → 0", app_settings._to_price(""), Decimal(0))
    check("_to_price '1500' → 1500", app_settings._to_price("1500"), Decimal("1500"))
    check("_to_price мусор → 0", app_settings._to_price("abc"), Decimal(0))

    # ── Две цены из настроек ─────────────────────────────────────────────────
    pool = FakePool({
        "subscription_entry_price": "2000",
        "subscription_renewal_price": "1500",
    })
    prices = asyncio.run(app_settings.subscription_prices(pool))
    check("вход из настроек", prices["entry"], Decimal("2000"))
    check("продление из настроек", prices["renewal"], Decimal("1500"))

    check("entry_rate", asyncio.run(tariffs.entry_rate(pool)), Decimal("2000"))
    check("renewal_rate", asyncio.run(tariffs.renewal_rate(pool)), Decimal("1500"))

    # ── Синтетическая «ступень» входа (без счёта мест) ───────────────────────
    tier = asyncio.run(tariffs.get_current_tier(pool, None))
    check("ступень: id=None (tier_id nullable)", tier["id"], None)
    check("ступень: цена = цена входа", tier["monthly_price"], Decimal("2000"))
    check("ступень: единственная", tier["tier_index"], 1)

    # Цена входа не задана (0) → продажа по нулю не допускается (экран «мест нет»).
    empty = FakePool({"subscription_renewal_price": "1500"})
    check("нет цены входа → None", asyncio.run(tariffs.get_current_tier(empty, None)), None)

    # ── Цена за срок = ставка × месяцы (матрицы ступеней больше нет) ──────────
    check("period_price 3 мес", asyncio.run(tariffs.period_price(None, None, tier, 3)),
          Decimal("6000"))
    durations = [
        {"id": 1, "months": 1, "unit": "month"},
        {"id": 2, "months": 3, "unit": "month"},
        {"id": 3, "months": 12, "unit": "month"},
    ]
    prices_map = asyncio.run(tariffs.prices_for(None, None, tier, durations))
    check("prices_for 1 мес", prices_map[1], Decimal("2000"))
    check("prices_for 3 мес", prices_map[2], Decimal("6000"))
    check("prices_for 12 мес", prices_map[3], Decimal("24000"))

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
