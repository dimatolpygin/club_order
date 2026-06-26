"""Изолированный smoke-тест чистой логики дашборда (этап 20).

Проверяет функции src.webadmin.stats без БД и сети:
- resolve_period: окна периодов и предыдущего периода равной длины;
- _nice_max / _fmt_axis_value: ровная шкала оси Y;
- delta_info: сравнение с предыдущим периодом (знак/проценты/деление на ноль);
- fmt_money: денежный формат;
- _axis: полный список корзин без пропусков;
- build_chart_svg: валидный SVG без NaN/inf и с нужными элементами.
Запуск: python -m tests.test_stats
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.webadmin import stats

NOW = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def check_true(name: str, cond) -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    assert cond, name


def main() -> None:
    # ── resolve_period ────────────────────────────────────────────────────────
    p, start, end, ps, pe, label, cf, ct = stats.resolve_period("30d", None, None, NOW, None)
    check("30d: период", p, "30d")
    check("30d: длина окна = 30 дней", (end - start), timedelta(days=30))
    check("30d: предыдущее окно той же длины", (pe - ps), timedelta(days=30))
    check("30d: предыдущее окно стыкуется", pe, start)

    p, start, end, ps, pe, *_ = stats.resolve_period("year", None, None, NOW, None)
    check("year: длина окна = 365 дней", (end - start), timedelta(days=365))
    check("year: предыдущее окно той же длины", (pe - ps), timedelta(days=365))

    first = NOW - timedelta(days=100)
    p, start, end, ps, pe, *_ = stats.resolve_period("all", None, None, NOW, first)
    check("all: без сравнения (prev=None)", (ps, pe), (None, None))
    check("all: старт от первого платежа (по дню)", start, first.replace(
        hour=0, minute=0, second=0, microsecond=0))

    # custom валидный
    p, start, end, ps, pe, label, cf, ct = stats.resolve_period(
        "custom", "2026-06-01", "2026-06-10", NOW, None)
    check("custom: период", p, "custom")
    check("custom: end = to + 1 день (включительно)", end,
          datetime(2026, 6, 11, tzinfo=timezone.utc))
    check("custom: длина 10 дней", (end - start), timedelta(days=10))
    check("custom: предыдущее окно той же длины", (pe - ps), (end - start))
    check("custom: refill from/to", (cf, ct), ("2026-06-01", "2026-06-10"))

    # custom невалидный (from>to) → откат к 30d
    p, *_ = stats.resolve_period("custom", "2026-06-10", "2026-06-01", NOW, None)
    check("custom невалидный → откат к 30d", p, "30d")
    p, *_ = stats.resolve_period("custom", "", "", NOW, None)
    check("custom пустой → откат к 30d", p, "30d")

    # неизвестный период → дефолт 30d
    p, *_ = stats.resolve_period("xyz", None, None, NOW, None)
    check("неизвестный период → 30d", p, "30d")

    # ── _nice_max ─────────────────────────────────────────────────────────────
    check("nice_max(0) = 1", stats._nice_max(0), 1.0)
    check("nice_max(7) = 10", stats._nice_max(7), 10)
    check("nice_max(1500) = 2000", stats._nice_max(1500), 2000)
    check("nice_max(3376) = 5000", stats._nice_max(3376), 5000)
    check_true("nice_max всегда >= value", all(
        stats._nice_max(v) >= v for v in (1, 9, 11, 99, 250, 4999, 123456)))

    # ── delta_info ────────────────────────────────────────────────────────────
    d = stats.delta_info(Decimal(150), Decimal(100))
    check("delta рост: up", (d["up"], d["down"]), (True, False))
    check("delta рост: +50%", d["pct_text"], "+50%")
    d = stats.delta_info(Decimal(80), Decimal(100))
    check("delta падение: down", (d["up"], d["down"]), (False, True))
    check("delta падение: знак минус (−)", d["pct_text"].startswith("−"), True)
    d = stats.delta_info(Decimal(100), Decimal(0))
    check("delta с нуля: +100%", d["pct_text"], "+100%")
    d = stats.delta_info(Decimal(0), Decimal(0))
    check("delta 0/0: прочерк", d["pct_text"], "—")

    # ── fmt_money ─────────────────────────────────────────────────────────────
    def norm(s: str) -> str:  # вид пробела (обычный/неразрывный) не важен
        return s.replace(" ", " ").replace(" ", " ")
    check("money: разряды + ₽", norm(stats.fmt_money(3396)), "3 396 ₽")
    check("money: округление до рубля", norm(stats.fmt_money(1075.36)), "1 075 ₽")
    check("money: ноль", norm(stats.fmt_money(0)), "0 ₽")
    check("money: None", norm(stats.fmt_money(None)), "0 ₽")

    # ── _axis ─────────────────────────────────────────────────────────────────
    axis_day = stats._axis(NOW - timedelta(days=5), NOW, "day")
    check_true("axis день: 5-6 корзин подряд", 5 <= len(axis_day) <= 6)
    check_true("axis день: шаг ровно сутки",
               all((axis_day[i + 1] - axis_day[i]) == timedelta(days=1)
                   for i in range(len(axis_day) - 1)))
    axis_month = stats._axis(datetime(2026, 1, 15, tzinfo=timezone.utc),
                             datetime(2026, 6, 10, tzinfo=timezone.utc), "month")
    check("axis месяц: 6 корзин (янв..июн)", len(axis_month), 6)
    check("axis месяц: первая = 1 января", axis_month[0],
          datetime(2026, 1, 1, tzinfo=timezone.utc))

    # ── build_chart_svg ───────────────────────────────────────────────────────
    labels = ["01.06", "02.06", "03.06"]
    svg = stats.build_chart_svg(labels, [100.0, 0.0, 250.0], [50.0, 80.0, 0.0])
    check_true("svg: открывается тегом <svg", svg.startswith("<svg"))
    check_true("svg: закрывается </svg>", svg.endswith("</svg>"))
    check_true("svg: нет nan/inf", "nan" not in svg.lower() and "inf" not in svg.lower())
    check_true("svg: есть линия текущего периода", "chart-line" in svg)
    check_true("svg: есть линия предыдущего периода", "chart-line-prev" in svg)
    check_true("svg: есть заливка area", "chart-area" in svg)
    check_true("svg: есть подписи осей", "chart-ytick" in svg and "chart-xtick" in svg)

    # без предыдущего периода — линии prev нет, но всё валидно
    svg2 = stats.build_chart_svg(labels, [0.0, 0.0, 0.0], None)
    check_true("svg(0): валиден без prev", svg2.startswith("<svg") and "chart-line-prev" not in svg2)
    check_true("svg(0): нет nan", "nan" not in svg2.lower())

    # одна точка (n=1) не должна делить на ноль
    svg3 = stats.build_chart_svg(["01.06"], [500.0], None)
    check_true("svg(n=1): валиден без деления на ноль",
               svg3.startswith("<svg") and "nan" not in svg3.lower())

    # ── build_donut_svg / _donut (этап 28) ────────────────────────────────────
    segs = [
        {"label": "A", "value": 1, "color": "#16a34a"},
        {"label": "B", "value": 1, "color": "#f59e0b"},
        {"label": "C", "value": 2, "color": "#94a3b8"},
    ]
    donut = stats.build_donut_svg(segs)
    check_true("donut: открывается <svg", donut.startswith("<svg"))
    check_true("donut: закрывается </svg>", donut.endswith("</svg>"))
    check_true("donut: нет nan/inf", "nan" not in donut.lower() and "inf" not in donut.lower())
    check("donut: 3 сегмента-окружности", donut.count("stroke-dasharray"), 3)
    check_true("donut: сумма в центре = 4", "<text" in donut and ">4<" in donut)

    # пустой donut (total=0): без сегментов, только серое кольцо, валидно
    empty = stats.build_donut_svg([{"label": "X", "value": 0, "color": "#000"}])
    check("donut(0): сегментов нет", empty.count("stroke-dasharray"), 0)
    check_true("donut(0): валиден", empty.startswith("<svg") and "nan" not in empty.lower())

    # _donut: проценты и сумма
    d = stats._donut("Тест", "k", segs)
    check("_donut: total", d["total"], 4)
    check("_donut: ключ", d["key"], "k")
    check("_donut: проценты сегментов", [round(l["pct"]) for l in d["legend"]], [25, 25, 50])

    # ── build_bar_svg / _bar (этап 29) ────────────────────────────────────────
    bar = stats.build_bar_svg(["01.06", "02.06", "03.06"], [3.0, 0.0, 5.0], "#16a34a")
    check_true("bar: открывается <svg", bar.startswith("<svg"))
    check_true("bar: закрывается </svg>", bar.endswith("</svg>"))
    check_true("bar: нет nan/inf", "nan" not in bar.lower() and "inf" not in bar.lower())
    check("bar: по столбику на корзину (нулевой — высотой 0)", bar.count("<rect"), 3)
    check_true("bar: есть оси/сетка", "chart-grid" in bar and "chart-axis" in bar)
    check_true("bar: подписи осей", "chart-ytick" in bar and "chart-xtick" in bar)

    # пустой/нулевой ряд не делит на ноль
    bar0 = stats.build_bar_svg(["01.06"], [0.0], "#000")
    check_true("bar(0): валиден без nan", bar0.startswith("<svg") and "nan" not in bar0.lower())
    bar_empty = stats.build_bar_svg([], [], "#000")
    check_true("bar([]): валиден без столбиков", bar_empty.startswith("<svg") and "<rect" not in bar_empty)

    b = stats._bar("Тест", "k", ["01.06", "02.06"], [2.0, 3.0], "#0ea5e9", 5)
    check("_bar: kind=bar", b["kind"], "bar")
    check("_bar: total передаётся как есть", b["total"], 5)
    check_true("_bar: svg валиден", b["svg"].startswith("<svg"))

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
