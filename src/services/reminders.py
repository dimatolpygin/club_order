"""Напоминания о продлении подписки (этап 6).

Фоновый джоб APScheduler проходит по активным подпискам и шлёт до трёх
напоминаний по мере приближения `end_date`:
  · early — «осталось N» (экран 14), порог `reminder_early_offset`;
  · soon  — «завтра заканчивается» (экран 15), порог `reminder_soon_offset`;
  · last  — «сегодня последний день» (экран 16), порог `reminder_last_offset`.

Пороги задаются в целых единицах `reminder_unit` (день по умолчанию; minute/hour/
day/month). Напоминание положено, когда целых единиц до конца осталось не больше
порога. Меньший порог = более срочное напоминание.

Защита от дублей двухуровневая: (1) факт отправки фиксируется строкой в
`subscription_reminders` через атомарный claim (ON CONFLICT DO NOTHING); (2) если
короткая подписка сразу попала в несколько окон (например, создана за день до
конца), за один проход шлётся ТОЛЬКО самое срочное напоминание, а более ранние,
«пропущенные», помечаются отправленными без рассылки — чтобы не слать стопку
устаревших сообщений.
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..utils import fmt_price
from . import app_settings

# Порядок типов от раннего к позднему.
REMINDER_KINDS = ("early", "soon", "last")
# Чем меньше ранг — тем срочнее напоминание (при равных порогах побеждает срочное).
_URGENCY = {"last": 0, "soon": 1, "early": 2}
# Сколько секунд в одной единице порога.
_UNIT_SECONDS = {"minute": 60, "hour": 3600, "day": 86400, "month": 30 * 86400}


def due_reminder_kinds(
    units_remaining: int, offsets: dict[str, int], sent: set[str]
) -> tuple[list[str], str | None]:
    """Чистая логика выбора напоминаний (без БД — удобно тестировать).

    Возвращает (eligible, to_send):
      eligible — типы, чьё окно открыто и которые ещё не отправлены (их нужно
                 «занять», чтобы не слать устаревшие позже);
      to_send  — единственный самый срочный тип, который реально отправляем
                 (или None, если отправлять нечего).
    """
    eligible = [
        k for k in REMINDER_KINDS
        if k not in sent and units_remaining <= offsets[k]
    ]
    if not eligible:
        return [], None
    to_send = min(eligible, key=lambda k: (offsets[k], _URGENCY[k]))
    return eligible, to_send


def _render(kind: str, row: asyncpg.Record, now: datetime) -> tuple[str, object]:
    """Текст и клавиатура для конкретного типа напоминания."""
    price = fmt_price(row["fixed_price"])
    if kind == "early":
        remaining = texts.remaining_phrase(row["end_date"], now, row["unit"])
        return (
            texts.reminder_early(price, row["end_date"], remaining),
            kb.reminder_early_kb(),
        )
    if kind == "soon":
        return texts.reminder_soon(price), kb.reminder_soon_kb()
    return texts.REMINDER_LAST, kb.reminder_last_kb()


async def run_reminder_check(pool: asyncpg.Pool, bot: Bot) -> None:
    """Фоновый проход: разослать причитающиеся напоминания о продлении."""
    cfg = await app_settings.reminder_config(pool)  # читаем на лету (правится в админке)
    unit_seconds = _UNIT_SECONDS.get(cfg["unit"], _UNIT_SECONDS["day"])
    offsets = cfg["offsets"]
    now = datetime.now(timezone.utc)

    rows = await repo.get_subscriptions_for_reminders(pool)
    for row in rows:
        remaining_secs = (row["end_date"] - now).total_seconds()
        units_remaining = int(remaining_secs // unit_seconds)
        eligible, to_send = due_reminder_kinds(
            units_remaining, offsets, set(row["sent"])
        )
        if to_send is None:
            continue

        for kind in eligible:
            # Занимаем все открытые окна, чтобы устаревшие не «выстрелили» позже,
            # но реально шлём только самое срочное.
            claimed = await repo.claim_reminder(pool, row["id"], kind)
            if kind != to_send or not claimed:
                continue
            text, markup = _render(kind, row, now)
            with suppress(Exception):  # пользователь мог заблокировать бота
                await bot.send_message(row["tg_id"], text, reply_markup=markup)
                logger.info(
                    f"🔔 Напоминание ({kind}) → @{row['username'] or '—'} "
                    f"(id:{row['tg_id']}, {row['first_name']})"
                )
