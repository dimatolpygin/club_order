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
from typing import Any

# Виды событий.
KIND_BANYA = "banya"
KIND_RETREAT = "retreat"

KIND_LABELS = {KIND_BANYA: "Энерго Баня", KIND_RETREAT: "Ретрит"}

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


def ticket_label(ticket_type: str) -> str:
    return TICKET_LABELS.get(ticket_type, ticket_type)


def visible_events(rows: Iterable[Mapping[str, Any]], now: datetime) -> list[Mapping[str, Any]]:
    """Отбирает события, видимые пользователю, по бизнес-правилам показа.

    - Только активные (`is_active`) и ещё не прошедшие (`starts_at >= now`).
    - Ретриты — показываем все.
    - Баня — только ближайшая по времени, плюс те, у кого стоит «показывать
      заранее» (`show_in_advance`). После даты ближайшей бани следующая
      становится ближайшей автоматически (прошедшие отфильтрованы по `now`).

    Результат отсортирован по дате начала (ближайшие — первыми).
    """
    upcoming = [
        e for e in rows
        if e["is_active"] and e["starts_at"] >= now
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
