"""Мелкие утилиты форматирования и дат."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from decimal import Decimal


def add_months(dt: datetime, months: int) -> datetime:
    """Прибавляет N месяцев к дате, корректно обрабатывая концы месяцев
    (31 января + 1 мес → 28/29 февраля)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_period(dt: datetime, n: int, unit: str = "months") -> datetime:
    """Прибавляет N единиц длительности. unit='minutes' (тест окончаний) → минуты,
    иначе — месяцы. Единица берётся из settings.subscription_unit."""
    if unit == "minutes":
        return dt + timedelta(minutes=n)
    return add_months(dt, n)


def fmt_price(value: Decimal | int | float | str) -> str:
    """Цена для показа: без копеек, если они нулевые. 1111.00 → «1 111», 1500.50 → «1 500,50»."""
    d = Decimal(str(value))
    if d == d.to_integral_value():
        n = int(d)
        return f"{n:,}".replace(",", " ")
    whole, frac = f"{d:.2f}".split(".")
    whole_spaced = f"{int(whole):,}".replace(",", " ")
    return f"{whole_spaced},{frac}"
