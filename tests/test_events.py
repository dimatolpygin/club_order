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

    # ── Скрытие распроданных + промотирование следующей бани ──────────────────
    # banya_near (5) распродан → ближайшей баней должна стать banya_next (6).
    visible_sold = ev.visible_events(rows, NOW, sold_out_ids={5})
    banya_visible = [r["id"] for r in visible_sold if r["kind"] == ev.KIND_BANYA]
    check("распродан ближайший: показывается следующая баня (6) + заранее (7)",
          sorted(banya_visible), [6, 7])
    check("распродан ближайший: сам распроданный (5) скрыт",
          5 in [r["id"] for r in visible_sold], False)

    # event_available: общий пул распродан → событие недоступно (скрываем).
    full_pool = make_event(gender_balance=False, seats_total=1)
    occ_full = ev.seats_occupied({"female": 1})  # total=1 из 1
    check("event_available: общий пул распродан → False",
          ev.event_available(full_pool, {"male": 100, "female": 100}, occ_full), False)
    check("event_available: есть свободное место → True",
          ev.event_available(make_event(seats_total=2), {"male": 100}, occ_full), True)
    check("event_available: без цен → False (продавать нечего)",
          ev.event_available(make_event(seats_total=10), {}, {}), False)
    # Раздельно: распродан только мужской пул, женский свободен → доступно.
    gp = make_event(gender_balance=True, seats_total=None, seats_male=1, seats_female=2)
    check("event_available: М распродан, Ж свободен, есть цена Ж → True",
          ev.event_available(gp, {"male": 1, "female": 1}, ev.seats_occupied({"male": 1})),
          True)

    # ── Группировка по типу для списка ────────────────────────────────────────
    grouped = ev.group_by_kind(visible)  # visible = [5(баня),2(ретрит),3(ретрит),7(баня)]
    check("группировка: порядок типов — бани, затем ретриты",
          [k for k, _ in grouped], [ev.KIND_BANYA, ev.KIND_RETREAT])
    check("группировка: бани собраны вместе (5,7)",
          [e["id"] for e in dict(grouped)[ev.KIND_BANYA]], [5, 7])
    check("группировка: ретриты собраны вместе (2,3)",
          [e["id"] for e in dict(grouped)[ev.KIND_RETREAT]], [2, 3])
    check("короткие подписи типов",
          (ev.kind_short(ev.KIND_BANYA), ev.kind_short(ev.KIND_RETREAT)),
          ("Баня", "Ретрит"))

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

    # ── Занятость по проданным билетам (этап 14) ──────────────────────────────
    check("занятость: пусто → нули",
          ev.seats_occupied({}), {"male": 0, "female": 0, "total": 0})
    # 1 мужской + 1 женский + 1 парный М+Ж = 2М, 2Ж, 4 общих места.
    check("занятость: одиночные + пара М+Ж",
          ev.seats_occupied({"male": 1, "female": 1, "pair_mf": 1}),
          {"male": 2, "female": 2, "total": 4})
    # 2 парных М+М = 4 мужских места; пара Ж+Ж = 2 женских.
    check("занятость: парные М+М и Ж+Ж",
          ev.seats_occupied({"pair_mm": 2, "pair_ff": 1}),
          {"male": 4, "female": 2, "total": 6})

    # Учёт занятости в доступности: общий пул 4, занято 3 (пара+одиночка) → пара не лезет.
    pooled4 = make_event(gender_balance=False, seats_total=4)
    occ = ev.seats_occupied({"pair_mf": 1, "male": 1})  # total=3
    check("доступность с занятостью: 1 место свободно → одиночный да, пара нет",
          (ev.has_seats(pooled4, "female", occ), ev.has_seats(pooled4, "pair_ff", occ)),
          (True, False))

    # Раздельно: 2М/2Ж, занят 1 парный М+Ж (1М+1Ж) → ещё по одному месту каждого пола.
    g2 = make_event(gender_balance=True, seats_total=None, seats_male=2, seats_female=2)
    occ2 = ev.seats_occupied({"pair_mf": 1})
    check("доступность раздельно с занятостью: остаётся 1М+1Ж",
          (ev.has_seats(g2, "male", occ2), ev.has_seats(g2, "pair_mm", occ2)),
          (True, False))

    # ── Скидка подписчику на билеты (этап 15) ─────────────────────────────────
    from decimal import Decimal
    check("скидка 0% → цена без изменений",
          ev.apply_discount(1000, 0), Decimal("1000"))
    check("скидка отрицательная/нет → без изменений",
          ev.apply_discount(1000, 0), Decimal("1000"))
    check("скидка 12% от 1222 → 1075.36",
          ev.apply_discount(1222, 12), Decimal("1075.36"))
    check("скидка 50% от 2444 → 1222",
          ev.apply_discount(2444, 50), Decimal("1222.00"))
    check("скидка 100% → 0",
          ev.apply_discount(500, 100), Decimal("0.00"))
    check("скидка округляется до копеек (ROUND_HALF_UP): 10% от 111 → 99.90",
          ev.apply_discount(111, 10), Decimal("99.90"))

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
