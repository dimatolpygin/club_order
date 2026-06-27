"""Изолированный smoke-тест построителя фильтров списка мероприятий (этап 36).

Проверяет events_repo._events_filters без БД: WHERE-условия и параметры для
поиск/направление/статус. Запуск: python -m tests.test_events_filter
"""
from __future__ import annotations

from src.webadmin import events_repo as r


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got!r} expected={expected!r}")
    assert got == expected, name


def main() -> None:
    # Без фильтров — только базовое условие времени, без параметров.
    where, params = r._events_filters("starts_at < now()", None, None, None)
    check("без фильтров: только время", where, "starts_at < now()")
    check("без фильтров: нет параметров", params, [])

    # Направление баня → kind = $1.
    where, params = r._events_filters("starts_at >= now()", None, "banya", None)
    check("направление banya: условие", "kind = $1" in where, True)
    check("направление banya: параметр", params, ["banya"])

    # Неизвестное направление игнорируется.
    where, params = r._events_filters("starts_at < now()", None, "xxx", None)
    check("направление мусор: нет kind", "kind" not in where, True)
    check("направление мусор: нет параметров", params, [])

    # Статусы.
    where, _ = r._events_filters("starts_at < now()", None, None, "active")
    check("статус active", "is_active = true AND canceled_at IS NULL" in where, True)
    where, _ = r._events_filters("starts_at < now()", None, None, "hidden")
    check("статус hidden", "is_active = false AND canceled_at IS NULL" in where, True)
    where, _ = r._events_filters("starts_at < now()", None, None, "canceled")
    check("статус canceled", "canceled_at IS NOT NULL" in where, True)

    # Поиск по названию — ILIKE.
    where, params = r._events_filters("starts_at < now()", "Баня", None, None)
    check("поиск: ILIKE по title", "title ILIKE $1" in where, True)
    check("поиск: параметр с %", params, ["%Баня%"])

    # Пустой поиск (пробелы) — без условия.
    where, params = r._events_filters("starts_at < now()", "   ", None, None)
    check("пустой поиск: без ILIKE", "ILIKE" not in where, True)
    check("пустой поиск: без параметров", params, [])

    # Комбинация направление + статус + поиск — сквозная нумерация параметров.
    where, params = r._events_filters("starts_at < now()", "ретрит", "retreat", "active")
    check("комбо: kind $1", "kind = $1" in where, True)
    check("комбо: поиск $2", "title ILIKE $2" in where, True)
    check("комбо: параметры по порядку", params, ["retreat", "%ретрит%"])

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
