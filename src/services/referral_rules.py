"""Правила реферальной программы по категориям покупок (этап 40).

С этапа 17 рефералка работала только на бани с двумя глобальными суммами. Теперь
суммы задаются **по категории** покупки (баня, ретрит, подписка, йога,
консультации), и для скидки новичку и бонуса пригласившему отдельно выбирается
**тип значения**: фиксированная сумма в рублях или процент от суммы покупки.
Хранилище — таблица `referral_rules` (SQL — в repo), здесь чистая логика: расчёт
сумм, справочники категорий и момент начисления. Без БД — покрыто smoke-тестом.

Момент начисления бонуса пригласившему:
  · билет (баня/ретрит) — ПОСЛЕ даты события (событие может быть возвращено);
  · подписка/йога/консультации — СРАЗУ после оплаты (даты у покупки нет).
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_DOWN, Decimal
from typing import Any

# Категории покупок, на которые распространяется реф-программа.
CATEGORY_BANYA = "banya"
CATEGORY_RETREAT = "retreat"
CATEGORY_SUBSCRIPTION = "subscription"
CATEGORY_YOGA = "yoga"
CATEGORY_CONSULT = "consult"

# Порядок определяет порядок в веб-админке.
CATEGORIES: tuple[str, ...] = (
    CATEGORY_BANYA, CATEGORY_RETREAT, CATEGORY_SUBSCRIPTION,
    CATEGORY_YOGA, CATEGORY_CONSULT,
)
CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_BANYA: "Баня",
    CATEGORY_RETREAT: "Ретрит",
    CATEGORY_SUBSCRIPTION: "Подписка",
    CATEGORY_YOGA: "Йога",
    CATEGORY_CONSULT: "Консультации",
}

# Типы значения: рубли или процент от суммы покупки.
KIND_FIXED = "fixed"
KIND_PERCENT = "percent"
KINDS: tuple[str, str] = (KIND_FIXED, KIND_PERCENT)
KIND_LABELS: dict[str, str] = {KIND_FIXED: "Сумма, ₽", KIND_PERCENT: "% от покупки"}

# Категории без даты события — бонус пригласившему начисляем сразу после оплаты.
INSTANT_CATEGORIES: frozenset[str] = frozenset(
    {CATEGORY_SUBSCRIPTION, CATEGORY_YOGA, CATEGORY_CONSULT}
)

# Дефолты (совпадают с этапом 17) — если строки правила в БД почему-то нет.
DEFAULT_DISCOUNT = 500
DEFAULT_BONUS = 1000


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def is_instant(category: str) -> bool:
    """Начислять бонус сразу после оплаты (нет даты события)?"""
    return category in INSTANT_CATEGORIES


def category_for_event_kind(kind: str) -> str:
    """Категория реф-правил по виду события (services.events.KIND_*)."""
    return CATEGORY_RETREAT if kind == "retreat" else CATEGORY_BANYA


def normalize_kind(raw: str | None) -> str:
    """Тип значения из формы админки; мусор → 'fixed' (безопасный дефолт)."""
    return raw if raw in KINDS else KIND_FIXED


def _amount(kind: str, value: Any, base: Any) -> int:
    """Значение правила в рублях: fixed → само значение, percent → % от `base`.

    Округление ВНИЗ до целого рубля (1 бонус = 1 ₽, дробных бонусов нет),
    отрицательные и нулевые значения → 0.
    """
    val = Decimal(str(value or 0))
    if val <= 0:
        return 0
    if kind == KIND_PERCENT:
        amount = Decimal(str(base or 0)) * val / Decimal(100)
    else:
        amount = val
    if amount <= 0:
        return 0
    return int(amount.to_integral_value(rounding=ROUND_DOWN))


def discount_for(rule: Mapping[str, Any] | None, base_price: Any) -> int:
    """Скидка новичку, ₽. Не больше цены покупки (в минус цена не уходит)."""
    if rule is None:
        return 0
    amount = _amount(rule["discount_kind"], rule["discount_value"], base_price)
    ceiling = int(Decimal(str(base_price or 0)).to_integral_value(rounding=ROUND_DOWN))
    return max(0, min(amount, ceiling))


def discount_phrase(rule: Mapping[str, Any] | None) -> str:
    """Величина скидки новичка для показа: «500 ₽» или «10%» (этап 40).

    Экран «Пригласить друга» один на все категории, поэтому показываем величину
    одной опорной категории (бани) — в боте при оформлении применится точная
    величина той категории, которую друг реально покупает.
    """
    if rule is None:
        return f"{DEFAULT_DISCOUNT} ₽"
    value = int(Decimal(str(rule["discount_value"] or 0)))
    return f"{value}%" if rule["discount_kind"] == KIND_PERCENT else f"{value} ₽"


def bonus_for(rule: Mapping[str, Any] | None, paid_amount: Any) -> int:
    """Бонус пригласившему, ₽ от суммы покупки друга.

    Фиксированный бонус НЕ ограничиваем суммой покупки: заказчик может дарить
    1000 ₽ за приглашение на покупку дешевле — это его решение.
    """
    if rule is None:
        return 0
    return _amount(rule["bonus_kind"], rule["bonus_value"], paid_amount)
