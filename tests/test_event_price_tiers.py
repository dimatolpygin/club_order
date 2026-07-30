"""Динамические цены ранним покупателям (этап 45).

Проверяет чистую логику `services.events`:
  · days_until_event — целых суток до события (вниз);
  · price_for_day    — цена момента по порогам «за N дней → цена».

Пример заказчика: за 7 дней — 1000, за 3 дня — 1500, в день события — 2000;
базовая цена типа — 900 (действует, пока до события больше недели).
Запуск: python -m tests.test_event_price_tiers
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services import events as ev


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    # ── days_until_event: целых суток вниз ──────────────────────────────────
    check("через 10.5 сут → 10", ev.days_until_event(now + timedelta(days=10, hours=12), now), 10)
    check("через 7.0 сут → 7", ev.days_until_event(now + timedelta(days=7), now), 7)
    check("сегодня (через 3 ч) → 0", ev.days_until_event(now + timedelta(hours=3), now), 0)
    check("событие прошло → -1", ev.days_until_event(now - timedelta(hours=1), now), -1)

    # ── price_for_day: пример заказчика (база 900) ──────────────────────────
    tiers = [(7, 1000), (3, 1500), (0, 2000)]
    base = 900
    check("за 10 дн → базовая 900", ev.price_for_day(base, tiers, 10), 900)
    check("за 8 дн → базовая 900", ev.price_for_day(base, tiers, 8), 900)
    check("за 7 дн → 1000", ev.price_for_day(base, tiers, 7), 1000)
    check("за 5 дн → 1000", ev.price_for_day(base, tiers, 5), 1000)
    check("за 3 дн → 1500", ev.price_for_day(base, tiers, 3), 1500)
    check("за 2 дн → 1500", ev.price_for_day(base, tiers, 2), 1500)
    check("за 1 дн → 1500", ev.price_for_day(base, tiers, 1), 1500)
    check("в день события → 2000", ev.price_for_day(base, tiers, 0), 2000)

    # ── Порогов нет → всегда базовая цена (нет регресса) ────────────────────
    check("без порогов → база", ev.price_for_day(1234, [], 3), 1234)

    # ── Цена растёт при приближении даты (монотонность) ─────────────────────
    seq = [ev.price_for_day(base, tiers, d) for d in (10, 7, 3, 0)]
    check("монотонно не убывает", all(a <= b for a, b in zip(seq, seq[1:])), True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
