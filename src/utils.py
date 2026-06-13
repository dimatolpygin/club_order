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


def add_period(dt: datetime, n: int, unit: str = "month") -> datetime:
    """Прибавляет N единиц длительности к дате. unit: minute/hour/day/month."""
    if unit == "minute":
        return dt + timedelta(minutes=n)
    if unit == "hour":
        return dt + timedelta(hours=n)
    if unit == "day":
        return dt + timedelta(days=n)
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
