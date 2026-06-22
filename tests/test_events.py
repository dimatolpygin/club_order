"""Изолированный smoke-тест логики раздела «Мероприятия» (этап 13).

Проверяет чистые функции services.events без БД и сети:
- visible_events: ретриты все; баня — ближайшая + «показывать заранее»;
  прошедшие и неактивные скрыты; автопереключение на следующую баню.
- seat_availability / has_seats: доступность по типам билетов с учётом
  гендер-баланса (общий пул vs раздельно М/Ж) и занятости.
Запуск: python -m tests.test_events
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services import events as ev

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def make_event(**over):
    base = {
        "id": 1,
        "kind": ev.KIND_RETREAT,
        "title": "Событие",
        "starts_at": NOW + timedelta(days=10),
        "gender_balance": False,
        "seats_total": 10,
        "seats_male": None,
        "seats_female": None,
        "show_in_advance": False,
        "subscriber_discount_percent": 0,
        "address": "",
        "rules_text": "",
        "is_active": True,
    }
    base.update(over)
    return base


def ids(rows) -> list[int]:
    return [r["id"] for r in rows]


def main() -> None:
    # ── Правила показа ────────────────────────────────────────────────────────
    past_retreat = make_event(id=1, kind=ev.KIND_RETREAT, starts_at=NOW - timedelta(days=1))
    retreat_a = make_event(id=2, kind=ev.KIND_RETREAT, starts_at=NOW + timedelta(days=5))
    retreat_b = make_event(id=3, kind=ev.KIND_RETREAT, starts_at=NOW + timedelta(days=30))
    inactive_retreat = make_event(id=4, kind=ev.KIND_RETREAT,
                                  starts_at=NOW + timedelta(days=7), is_active=False)
    banya_near = make_event(id=5, kind=ev.KIND_BANYA, starts_at=NOW + timedelta(days=2))
    banya_next = make_event(id=6, kind=ev.KIND_BANYA, starts_at=NOW + timedelta(days=9))
    banya_far_adv = make_event(id=7, kind=ev.KIND_BANYA,
                               starts_at=NOW + timedelta(days=40), show_in_advance=True)
    banya_past = make_event(id=8, kind=ev.KIND_BANYA, starts_at=NOW - timedelta(days=3))

    rows = [past_retreat, retreat_a, retreat_b, inactive_retreat,
            banya_near, banya_next, banya_far_adv, banya_past]
    visible = ev.visible_events(rows, NOW)

    # Прошедшие (1, 8) и неактивные (4) скрыты; обычная не-ближайшая баня (6) скрыта.
    # Видны: ретриты 2,3; ближайшая баня 5; баня «заранее» 7. Сортировка по дате.
    check("показ: состав по правилам (сорт по дате)", ids(visible), [5, 2, 3, 7])

    # Ретриты показываются все будущие активные.
    check("ретриты: оба будущих видны",
          all(rid in ids(visible) for rid in (2, 3)), True)

    # Автопереключение: ближайшая баня прошла → следующая становится ближайшей.
    later = NOW + timedelta(days=3)  # banya_near (день 2) уже в прошлом
    visible_later = ev.visible_events(rows, later)
    banya_ids_later = [r["id"] for r in visible_later if r["kind"] == ev.KIND_BANYA]
    check("баня: после даты ближайшей показывается следующая (6) + заранее (7)",
          sorted(banya_ids_later), [6, 7])

    # Нет будущих событий → пусто.
    check("показ: только прошедшие → пусто",
          ev.visible_events([past_retreat, banya_past], NOW), [])

    # ── Доступность мест: общий пул ───────────────────────────────────────────
    pooled = make_event(gender_balance=False, seats_total=3)
    check("общий пул: одиночный билет — место есть",
          ev.has_seats(pooled, "male"), True)
    check("общий пул: парный (нужно 2) — места есть (3≥2)",
          ev.has_seats(pooled, "pair_mf"), True)
    check("общий пул: парный при 1 свободном месте — мест нет",
          ev.has_seats(make_event(seats_total=1), "pair_mm"), False)
    check("общий пул: занято всё → одиночный недоступен",
          ev.has_seats(pooled, "female", {"total": 3}), False)

    # ── Доступность мест: раздельно М/Ж ───────────────────────────────────────
    gendered = make_event(gender_balance=True, seats_total=None,
                          seats_male=2, seats_female=1)
    check("раздельно: мужской — место есть", ev.has_seats(gendered, "male"), True)
    check("раздельно: женский — место есть", ev.has_seats(gendered, "female"), True)
    check("раздельно: пара М+Ж (1М+1Ж) — есть", ev.has_seats(gendered, "pair_mf"), True)
    check("раздельно: пара Ж+Ж (нужно 2Ж, есть 1) — мест нет",
          ev.has_seats(gendered, "pair_ff"), False)
    check("раздельно: пара М+М (нужно 2М, есть 2) — есть",
          ev.has_seats(gendered, "pair_mm"), True)
    check("раздельно: занят 1 муж → пара М+М недоступна",
          ev.has_seats(gendered, "pair_mm", {"male": 1}), False)

    # ── Меню билетов: только типы с ценой, в каноничном порядке ────────────────
    prices = {"female": 3000, "male": 2500, "pair_mm": 5000}
    items = ev.seat_availability(gendered, prices)
    check("меню: только заданные типы, порядок TICKET_TYPES",
          [t for t, _, _ in items], ["male", "female", "pair_mm"])
    check("меню: доступность (М есть, Ж есть, М+М есть)",
          [a for _, _, a in items], [True, True, True])

    # Тип без цены не попадает в меню; распроданный помечается недоступным.
    sold = make_event(gender_balance=True, seats_total=None, seats_male=0, seats_female=1)
    items_sold = ev.seat_availability(sold, {"male": 1000, "female": 2000})
    check("меню: мужских мест 0 → male недоступен, female доступен",
          [(t, a) for t, _, a in items_sold], [("male", False), ("female", True)])

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
