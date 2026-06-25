"""Дашборд статистики (этап 20).

Доход за период со сравнением с предыдущим периодом равной длины; общий и по
направлениям (подписка / бани / ретриты); активные подписчики; эффективность
рефералки. График дохода — серверный inline-SVG (синий — текущий период, зелёный —
предыдущий), без внешних JS-библиотек и без артефактов по осям.

Периоды:
  · 30d   — последние 30 дней (по умолчанию), сравнение с предыдущими 30 днями;
  · year  — последние 365 дней, сравнение с предыдущими 365 днями;
  · all   — всё время (от первого платежа), без сравнения;
  · custom — произвольный диапазон [from, to], сравнение с окном той же длины до from.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Request

from ..db import get_pool
from .deps import current_admin, templates
from . import stats_repo

router = APIRouter()

# Человекочитаемые подписи направлений дохода.
DIRECTION_LABELS = {
    "subscription": "Подписки 11:11",
    "banya": "Билеты · Баня",
    "retreat": "Билеты · Ретриты",
    "ticket": "Билеты · Прочее",
}
DIRECTION_ORDER = ("subscription", "banya", "retreat", "ticket")
DIRECTION_COLORS = {
    "subscription": "#2563eb",
    "banya": "#16a34a",
    "retreat": "#0ea5e9",
    "ticket": "#9333ea",
}

PERIOD_LABELS = {"30d": "30 дней", "year": "Год", "all": "Всё время", "custom": "Период"}
_RU_MONTHS_SHORT = (
    "", "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


# ── Период ───────────────────────────────────────────────────────────────────
def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc)


def resolve_period(
    period: str, frm: str | None, to: str | None, now: datetime,
    first_payment: datetime | None,
):
    """Возвращает (period, start, end, prev_start, prev_end, label, custom_from, custom_to).

    prev_start/prev_end = None → сравнение не показываем (режим «всё время»).
    end — правая граница (исключительная).
    """
    if period == "year":
        start, end = now - timedelta(days=365), now
        return "year", start, end, start - timedelta(days=365), start, "Год", None, None
    if period == "all":
        start = (first_payment or now).replace(hour=0, minute=0, second=0, microsecond=0)
        return "all", start, now, None, None, "Всё время", None, None
    if period == "custom":
        d_from = _parse_date(frm)
        d_to = _parse_date(to)
        if d_from and d_to and d_from <= d_to:
            start = d_from
            end = d_to + timedelta(days=1)  # включительно по выбранную дату
            span = end - start
            label = f"{start:%d.%m.%Y} – {d_to:%d.%m.%Y}"
            return ("custom", start, end, start - span, start, label,
                    frm.strip(), to.strip())
        # некорректный диапазон → откатываемся к 30 дням
    # 30d (дефолт)
    start, end = now - timedelta(days=30), now
    return "30d", start, end, start - timedelta(days=30), start, "30 дней", None, None


# ── Корзины времени для графика ──────────────────────────────────────────────
def _trunc(dt: datetime, gran: str) -> datetime:
    dt = dt.replace(minute=0, second=0, microsecond=0)
    if gran == "month":
        return dt.replace(day=1, hour=0)
    return dt.replace(hour=0)


def _next_bucket(dt: datetime, gran: str) -> datetime:
    if gran == "month":
        return dt.replace(year=dt.year + 1, month=1) if dt.month == 12 \
            else dt.replace(month=dt.month + 1)
    return dt + timedelta(days=1)


def _axis(start: datetime, end: datetime, gran: str) -> list[datetime]:
    """Полный список начал корзин в [start, end) — чтобы пустые шли нулями."""
    out: list[datetime] = []
    cur = _trunc(start, gran)
    # первая корзина может начаться чуть раньше start — нормально для оси.
    while cur < end:
        out.append(cur)
        cur = _next_bucket(cur, gran)
    return out


def _series(buckets: dict[datetime, Decimal], axis: list[datetime]) -> list[float]:
    return [float(buckets.get(b, 0) or 0) for b in axis]


def _bucket_label(dt: datetime, gran: str) -> str:
    if gran == "month":
        return f"{_RU_MONTHS_SHORT[dt.month]} {dt.year % 100:02d}"
    return f"{dt.day:02d}.{dt.month:02d}"


# ── SVG-график ───────────────────────────────────────────────────────────────
def _nice_max(value: float) -> float:
    """Округляет максимум вверх до «красивого» (1/2/5 × 10^k) — ровная шкала."""
    if value <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if value <= m * base:
            return m * base
    return 10 * base


def _fmt_axis_value(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:g}М"
    if v >= 1_000:
        return f"{v / 1_000:g}к"
    return f"{v:g}"


def build_chart_svg(
    labels: list[str], current: list[float], previous: list[float] | None
) -> str:
    """Строит inline-SVG: синяя линия+заливка (текущий период) и зелёная пунктирная
    (предыдущий, если задан). Оси чистые: базовая линия, 4 сетки с подписями."""
    W, H = 760, 260
    pad_l, pad_r, pad_t, pad_b = 52, 14, 14, 30
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_t - pad_b
    n = len(current)

    peak = max([*current, *(previous or []), 0.0])
    top = _nice_max(peak)

    def x(i: int) -> float:
        if n <= 1:
            return pad_l + plot_w / 2
        return pad_l + plot_w * i / (n - 1)

    def y(v: float) -> float:
        return pad_t + plot_h * (1 - v / top)

    parts: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" class="chart-svg" role="img" '
        f'preserveAspectRatio="xMidYMid meet">'
    ]

    # Горизонтальная сетка + подписи Y (5 линий: 0..top).
    for k in range(5):
        v = top * k / 4
        yy = y(v)
        parts.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{W - pad_r}" y2="{yy:.1f}" '
            f'class="chart-grid"/>'
        )
        parts.append(
            f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" class="chart-ytick" '
            f'text-anchor="end">{_fmt_axis_value(v)}</text>'
        )

    # Предыдущий период — зелёная пунктирная линия (без заливки).
    if previous and any(previous):
        pts_prev = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(previous))
        parts.append(f'<polyline points="{pts_prev}" class="chart-line-prev"/>')

    # Текущий период — синяя заливка + линия.
    if n >= 1:
        area = (
            f"{x(0):.1f},{y(0):.1f} "
            + " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(current))
            + f" {x(n - 1):.1f},{y(0):.1f}"
        )
        parts.append(f'<polygon points="{area}" class="chart-area"/>')
        pts_cur = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(current))
        parts.append(f'<polyline points="{pts_cur}" class="chart-line"/>')

    # Базовая ось X.
    parts.append(
        f'<line x1="{pad_l}" y1="{y(0):.1f}" x2="{W - pad_r}" y2="{y(0):.1f}" '
        f'class="chart-axis"/>'
    )

    # Подписи X: не более ~7, равномерно.
    if n:
        step = max(1, round(n / 7))
        for i in range(0, n, step):
            parts.append(
                f'<text x="{x(i):.1f}" y="{H - 8}" class="chart-xtick" '
                f'text-anchor="middle">{labels[i]}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


# ── Форматирование ───────────────────────────────────────────────────────────
def fmt_money(v) -> str:
    """1234567.5 → '1 234 568 ₽' (без копеек, неразрывные пробелы тысяч)."""
    n = int(round(float(v or 0)))
    s = f"{n:,}".replace(",", " ")
    return f"{s} ₽"


def delta_info(cur: Decimal, prev: Decimal) -> dict:
    """Сравнение с предыдущим периодом: знак, проценты, направление."""
    cur_f, prev_f = float(cur or 0), float(prev or 0)
    diff = cur_f - prev_f
    if prev_f == 0:
        pct = None if cur_f == 0 else 100.0
    else:
        pct = diff / prev_f * 100
    return {
        "diff": diff,
        "pct": pct,
        "up": diff > 0,
        "down": diff < 0,
        "pct_text": "—" if pct is None else f"{'+' if pct >= 0 else '−'}{abs(pct):.0f}%",
    }


# ── Маршрут ──────────────────────────────────────────────────────────────────
@router.get("/")
async def dashboard(request: Request):
    admin = current_admin(request)
    period = request.query_params.get("period", "30d")
    frm = request.query_params.get("from")
    to = request.query_params.get("to")
    pool = get_pool()
    now = datetime.now(timezone.utc)
    first_payment = await stats_repo.first_payment_at(pool)

    period, start, end, prev_start, prev_end, label, cf, ct = resolve_period(
        period, frm, to, now, first_payment
    )

    total = await stats_repo.revenue_total(pool, start, end)
    by_dir = await stats_repo.revenue_by_direction(pool, start, end)
    pay_count = await stats_repo.payments_count(pool, start, end)
    subs = await stats_repo.active_subscribers(pool)
    ref = await stats_repo.referral_stats(pool, start, end)

    # Сравнение с предыдущим периодом (если режим его предполагает).
    has_prev = prev_start is not None
    prev_total = await stats_repo.revenue_total(pool, prev_start, prev_end) \
        if has_prev else Decimal(0)

    # График: единая гранулярность для текущего и предыдущего периодов.
    span_days = max(1, (end - start).days)
    gran = "day" if span_days <= 92 else "month"
    axis = _axis(start, end, gran)
    cur_buckets = await stats_repo.revenue_buckets(pool, start, end, gran)
    cur_series = _series(cur_buckets, axis)
    if has_prev:
        prev_axis = _axis(prev_start, prev_end, gran)
        prev_buckets = await stats_repo.revenue_buckets(pool, prev_start, prev_end, gran)
        prev_series = _series(prev_buckets, prev_axis)
        # выравниваем по длине текущей оси (для наложения по индексу корзины)
        prev_series = (prev_series + [0.0] * len(axis))[: len(axis)]
    else:
        prev_series = None
    chart_labels = [_bucket_label(b, gran) for b in axis]
    chart_svg = build_chart_svg(chart_labels, cur_series, prev_series)

    # Направления в фиксированном порядке (только ненулевые скрывать не будем —
    # показываем все известные, чтобы структура была стабильной).
    directions = []
    for key in DIRECTION_ORDER:
        amount = by_dir.get(key, Decimal(0))
        if key == "ticket" and not amount:
            continue  # «прочие события» показываем только если есть
        directions.append({
            "key": key,
            "label": DIRECTION_LABELS[key],
            "color": DIRECTION_COLORS[key],
            "amount": amount,
            "amount_text": fmt_money(amount),
            "pct": (float(amount) / float(total) * 100) if total else 0,
        })

    avg_check = (float(total) / pay_count) if pay_count else 0

    ctx = {
        "active": "dashboard",
        "admin": admin,
        "period": period,
        "period_label": label,
        "custom_from": cf or "",
        "custom_to": ct or "",
        "total_text": fmt_money(total),
        "has_prev": has_prev,
        "delta": delta_info(total, prev_total) if has_prev else None,
        "prev_total_text": fmt_money(prev_total),
        "directions": directions,
        "subs": subs,
        "pay_count": pay_count,
        "avg_check_text": fmt_money(avg_check),
        "ref": ref,
        "ref_bonus_text": fmt_money(ref["bonus_paid"]),
        "chart_svg": chart_svg,
        "period_options": PERIOD_LABELS,
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)
