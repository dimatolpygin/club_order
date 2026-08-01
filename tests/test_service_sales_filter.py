"""Изолированный smoke-тест построителя фильтров журнала продаж услуг (этап 51).

Проверяет repo._service_sales_filters без БД: WHERE-условия, параметры и сквозную
нумерацию $-параметров для категория/поиск/формат-пакет/период.
Запуск: python -m tests.test_service_sales_filter
"""
from __future__ import annotations

from datetime import date

from src import repo


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got!r} expected={expected!r}")
    assert got == expected, name


def main() -> None:
    # База: категория = $1, только успешные оплаты услуги.
    where, params = repo._service_sales_filters("yoga", None, None)
    check("база: kind service", "p.kind = 'service'" in where, True)
    check("база: succeeded", "p.status = 'succeeded'" in where, True)
    check("база: категория $1", "sp.category = $1" in where, True)
    check("база: параметр категории", params, ["yoga"])

    # Формат/пакет по коду → $2.
    where, params = repo._service_sales_filters("yoga", None, "individual")
    check("формат: sp.code $2", "sp.code = $2" in where, True)
    check("формат: параметры", params, ["yoga", "individual"])

    # Диапазон даты покупки.
    where, params = repo._service_sales_filters(
        "consult", None, None, date(2026, 8, 1), date(2026, 8, 31)
    )
    check("период: from $2", "p.created_at::date >= $2" in where, True)
    check("период: to $3", "p.created_at::date <= $3" in where, True)
    check("период: параметры", params, ["consult", date(2026, 8, 1), date(2026, 8, 31)])

    # Поиск по покупателю — username/first_name/tg_id одним параметром.
    where, params = repo._service_sales_filters("yoga", "Аня", None)
    check("поиск: username", "u.username ILIKE $2" in where, True)
    check("поиск: first_name", "u.first_name ILIKE $2" in where, True)
    check("поиск: tg_id как текст", "CAST(p.tg_id AS TEXT) LIKE $2" in where, True)
    check("поиск: параметр с %", params, ["yoga", "%Аня%"])

    # Число в поиске → ещё и точный номер платежа отдельным параметром.
    where, params = repo._service_sales_filters("yoga", "123", None)
    check("поиск-число: p.id как доп. условие", "OR p.id = $3" in where, True)
    check("поиск-число: параметры", params, ["yoga", "%123%", 123])

    # #N — точный номер платежа, без ILIKE.
    where, params = repo._service_sales_filters("yoga", "#42", None)
    check("#N: точный p.id", "p.id = $2" in where, True)
    check("#N: нет ILIKE", "ILIKE" in where, False)
    check("#N: параметры", params, ["yoga", 42])

    # Пустой поиск (пробелы) не добавляет условие.
    where, params = repo._service_sales_filters("consult", "   ", None)
    check("пустой поиск: нет ILIKE", "ILIKE" in where, False)
    check("пустой поиск: только категория", params, ["consult"])

    # Комбо: категория + формат + период + поиск — нумерация по порядку.
    where, params = repo._service_sales_filters(
        "consult", "иван", "p4", date(2026, 8, 1), None
    )
    check("комбо: код $2", "sp.code = $2" in where, True)
    check("комбо: from $3", "p.created_at::date >= $3" in where, True)
    check("комбо: поиск $4", "ILIKE $4" in where, True)
    check("комбо: параметры по порядку", params, ["consult", "p4", date(2026, 8, 1), "%иван%"])

    print("\nВсе проверки построителя фильтров журнала продаж пройдены.")


if __name__ == "__main__":
    main()
