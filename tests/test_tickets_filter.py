"""Изолированный smoke-тест построителя фильтров списка билетов (этап 32).

Проверяет repo._sold_tickets_filters без БД: какие WHERE-условия и параметры
получаются для событие/поиск/статус. Запуск: python -m tests.test_tickets_filter
"""
from __future__ import annotations

from src import repo


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got!r} expected={expected!r}")
    assert got == expected, name


def main() -> None:
    # Без фильтров — только базовое условие, без параметров.
    where, params = repo._sold_tickets_filters(None, None, None)
    check("без фильтров: базовое условие", "t.status IN ('paid', 'refunded')" in where, True)
    check("без фильтров: нет параметров", params, [])

    # Событие → параметр $1.
    where, params = repo._sold_tickets_filters(5, None, None)
    check("событие: условие", "t.event_id = $1" in where, True)
    check("событие: параметр", params, [5])

    # Статусы.
    where, _ = repo._sold_tickets_filters(None, None, "paid")
    check("статус paid: без запроса возврата", "refund_requested = false" in where, True)
    where, _ = repo._sold_tickets_filters(None, None, "refund_requested")
    check("статус refund_requested", "refund_requested = true" in where, True)
    where, _ = repo._sold_tickets_filters(None, None, "refunded")
    check("статус refunded", "t.status = 'refunded'" in where, True)

    # Поиск — по username/first_name/tg_id одним параметром (ILIKE).
    where, params = repo._sold_tickets_filters(None, "Gats", None)
    check("поиск: username", "u.username ILIKE $1" in where, True)
    check("поиск: first_name", "u.first_name ILIKE $1" in where, True)
    check("поиск: tg_id как текст", "CAST(t.tg_id AS TEXT) LIKE $1" in where, True)
    check("поиск: параметр с %", params, ["%Gats%"])

    # Комбинация событие + поиск — корректная нумерация параметров.
    where, params = repo._sold_tickets_filters(7, "ив", "refunded")
    check("комбо: событие $1", "t.event_id = $1" in where, True)
    check("комбо: поиск $2", "ILIKE $2" in where, True)
    check("комбо: параметры по порядку", params, [7, "%ив%"])

    # Пустой поиск (пробелы) не добавляет условие.
    where, params = repo._sold_tickets_filters(None, "   ", None)
    check("пустой поиск: без ILIKE", "ILIKE" not in where, True)
    check("пустой поиск: без параметров", params, [])

    # Фильтр по дате покупки (диапазон, включительно).
    import datetime as _dt
    d1, d2 = _dt.date(2026, 6, 23), _dt.date(2026, 6, 25)
    where, params = repo._sold_tickets_filters(None, None, None, d1, d2)
    check("дата от: >= $1", "t.created_at::date >= $1" in where, True)
    check("дата до: <= $2", "t.created_at::date <= $2" in where, True)
    check("дата: параметры по порядку", params, [d1, d2])

    # Только «дата до» — один параметр.
    where, params = repo._sold_tickets_filters(None, None, None, None, d2)
    check("только дата до: один параметр", params, [d2])
    check("только дата до: без >=", ">=" not in where, True)

    # Комбинация событие + дата + поиск — сквозная нумерация параметров.
    where, params = repo._sold_tickets_filters(7, "Gats", None, d1, None)
    check("комбо событие+дата+поиск: параметры", params, [7, d1, "%Gats%"])
    check("комбо: поиск получил $3", "ILIKE $3" in where, True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
