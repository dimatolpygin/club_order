"""Бизнес-логика раздела «Мероприятия» в боте (этап 13).

Чистые функции поверх данных этапа 12 (`events` + `event_ticket_prices`):
правила показа событий пользователю и доступность мест по типам билетов.
Отделены от хендлеров, чтобы покрыть smoke-тестом без БД/Telegram.

Учёт занятых мест по проданным билетам появится на этапе 14 (таблицы `tickets`
ещё нет). Поэтому `seat_availability` принимает занятость опционально; пока её
передают пустой → доступность считается по сконфигурированной вместимости.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Виды событий.
KIND_BANYA = "banya"
KIND_RETREAT = "retreat"

KIND_LABELS = {KIND_BANYA: "Энерго Баня", KIND_RETREAT: "Ретрит"}
# Короткая подпись типа для компактных кнопок списка.
KIND_SHORT = {KIND_BANYA: "Баня", KIND_RETREAT: "Ретрит"}
# Порядок групп в списке: сначала бани, потом ретриты, затем прочее.
KIND_ORDER = (KIND_BANYA, KIND_RETREAT)

# Типы билетов в порядке показа и их подписи.
TICKET_TYPES = ("male", "female", "pair_mf", "pair_ff", "pair_mm")
TICKET_LABELS = {
    "male": "Мужской",
    "female": "Женский",
    "pair_mf": "Парный (М+Ж)",
    "pair_ff": "Парный (Ж+Ж)",
    "pair_mm": "Парный (М+М)",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def kind_short(kind: str) -> str:
    return KIND_SHORT.get(kind, kind)


def group_by_kind(
    events: Iterable[Mapping[str, Any]]
) -> list[tuple[str, list[Mapping[str, Any]]]]:
    """Группирует события по типу для показа в списке с заголовками.

    Порядок групп — KIND_ORDER (бани, ретриты), затем прочие типы по алфавиту.
    Внутри группы — как пришло (visible_events уже сортирует по дате).
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for e in events:
        groups.setdefault(e["kind"], []).append(e)

    ordered_kinds = [k for k in KIND_ORDER if k in groups]
    ordered_kinds += sorted(k for k in groups if k not in KIND_ORDER)
    return [(k, groups[k]) for k in ordered_kinds]


def ticket_label(ticket_type: str) -> str:
    return TICKET_LABELS.get(ticket_type, ticket_type)


def visible_events(
    rows: Iterable[Mapping[str, Any]],
    now: datetime,
    sold_out_ids: frozenset[int] | set[int] = frozenset(),
) -> list[Mapping[str, Any]]:
    """Отбирает события, видимые пользователю, по бизнес-правилам показа.

    - Только активные (`is_active`) и ещё не прошедшие (`starts_at >= now`).
    - Полностью распроданные (`sold_out_ids`) скрываются — чтобы «ближайшей»
      баней стала ближайшая баня СО СВОБОДНЫМИ местами, а не висела распроданная.
    - Ретриты — показываем все (оставшиеся после фильтра распроданных).
    - Баня — только ближайшая по времени, плюс те, у кого стоит «показывать
      заранее» (`show_in_advance`). После даты ближайшей бани следующая
      становится ближайшей автоматически (прошедшие отфильтрованы по `now`).

    Результат отсортирован по дате начала (ближайшие — первыми).
    """
    upcoming = [
        e for e in rows
        if e["is_active"] and e["starts_at"] >= now and e["id"] not in sold_out_ids
    ]

    banyas = sorted(
        (e for e in upcoming if e["kind"] == KIND_BANYA),
        key=lambda e: e["starts_at"],
    )
    nearest_banya_id = banyas[0]["id"] if banyas else None

    shown: list[Mapping[str, Any]] = []
    for e in upcoming:
        if e["kind"] == KIND_BANYA:
            if e["id"] == nearest_banya_id or e["show_in_advance"]:
                shown.append(e)
        else:
            # Ретриты и любые иные виды — показываем все будущие активные.
            shown.append(e)

    shown.sort(key=lambda e: e["starts_at"])
    return shown


def _required_seats(ticket_type: str) -> tuple[int, int, int]:
    """Сколько мест нужно билету: (мужских, женских, общих).

    Для раздельного учёта смотрим мужские/женские; для общего пула — сумму.
    """
    if ticket_type == "male":
        return 1, 0, 1
    if ticket_type == "female":
        return 0, 1, 1
    if ticket_type == "pair_mf":
        return 1, 1, 2
    if ticket_type == "pair_ff":
        return 0, 2, 2
    if ticket_type == "pair_mm":
        return 2, 0, 2
    return 0, 0, 0


def has_seats(
    event: Mapping[str, Any],
    ticket_type: str,
    occupied: Mapping[str, int] | None = None,
) -> bool:
    """Есть ли свободные места под этот тип билета.

    `occupied` — занято мест: ключи `total`/`male`/`female` (этап 14). Если не
    передано, считаем занятость нулевой (этап 13 — учёта проданных билетов нет).
    """
    occ = occupied or {}
    need_m, need_f, need_total = _required_seats(ticket_type)

    if not event["gender_balance"]:
        cap = (event["seats_total"] or 0) - occ.get("total", 0)
        return cap >= need_total

    free_m = (event["seats_male"] or 0) - occ.get("male", 0)
    free_f = (event["seats_female"] or 0) - occ.get("female", 0)
    return free_m >= need_m and free_f >= need_f


def seats_occupied(counts: Mapping[str, int]) -> dict[str, int]:
    """Занятые места по проданным билетам: {male, female, total}.

    `counts` — число билетов по типам ({ticket_type: count}). Парный билет
    занимает 2 места (М+Ж = 1М+1Ж, Ж+Ж = 2Ж, М+М = 2М), одиночный — 1 место
    своего пола. `total` — сумма для событий с общим пулом мест.
    """
    male = female = total = 0
    for ttype, c in counts.items():
        nm, nf, ntot = _required_seats(ttype)
        male += c * nm
        female += c * nf
        total += c * ntot
    return {"male": male, "female": female, "total": total}


def apply_discount(price: int | Decimal, percent: int) -> Decimal:
    """Цена со скидкой подписчика, % (0..100). Округление до копеек (ROUND_HALF_UP).

    Скидка ≤0 — цена без изменений; ≥100 — цена 0 (страховка, админ валидирует 0..100).
    Едина для показа и для суммы платежа, чтобы цифры на экране и в чеке совпадали.
    """
    base = Decimal(str(price))
    if not percent or percent <= 0:
        return base
    if percent >= 100:
        return Decimal("0.00")
    discounted = base * (Decimal(100) - Decimal(percent)) / Decimal(100)
    return discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def best_ticket_price(
    price: int | Decimal, *, subscriber_pct: int = 0, promo_pct: int = 0
) -> tuple[Decimal, str]:
    """Лучшая цена билета: скидка подписчика и промокод НЕ суммируются (этап 16).

    Берётся та скидка, что даёт МЕНЬШУЮ итоговую цену (большую выгоду клиенту).
    Пример: 1000 ₽, подписка −10% (900) vs промокод −5% (950) → 900 ₽ (подписка).

    Возвращает (итоговая_цена, applied), где applied:
      'promo'      — выиграл промокод (расходуем активацию);
      'subscriber' — выиграла скидка подписчика (промокод НЕ расходуется);
      'none'       — ни одна скидка не уменьшает цену.

    На равенстве предпочитаем скидку подписчика — чтобы не тратить активацию
    промокода зря (одинаковую выгоду даёт и она). Обе скидки — проценты 0..100;
    `fixed_price`-промокоды на билеты не применяются (фильтруется выше по стеку).
    """
    base = Decimal(str(price))
    sub_price = apply_discount(base, subscriber_pct)
    promo_price = apply_discount(base, promo_pct)
    if promo_pct > 0 and promo_price < sub_price:
        return promo_price, "promo"
    if subscriber_pct > 0 and sub_price < base:
        return sub_price, "subscriber"
    if promo_pct > 0 and promo_price < base:
        return promo_price, "promo"
    return base, "none"


def event_available(
    event: Mapping[str, Any],
    prices: Mapping[str, int],
    occupied: Mapping[str, int] | None = None,
) -> bool:
    """Есть ли у события хоть один продаваемый тип билета со свободным местом.

    Учитываются только типы с заданной ценой. False → событие полностью
    распродано (или вовсе без цен) → скрываем из списка в боте.
    """
    return any(has_seats(event, ttype, occupied) for ttype in prices)


def seat_availability(
    event: Mapping[str, Any],
    prices: Mapping[str, int],
    occupied: Mapping[str, int] | None = None,
) -> list[tuple[str, int, bool]]:
    """Меню типов билетов события: только типы с заданной ценой.

    Возвращает список `(ticket_type, price, available)` в порядке `TICKET_TYPES`.
    `available=False` → у типа кончились места (на экране — «Мест нет»).
    """
    out: list[tuple[str, int, bool]] = []
    for ttype in TICKET_TYPES:
        if ttype not in prices:
            continue
        out.append((ttype, prices[ttype], has_seats(event, ttype, occupied)))
    return out
