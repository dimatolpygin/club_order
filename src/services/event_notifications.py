"""Уведомления по событиям (этап 20).

Фоновый джоб APScheduler выполняет два действия за один проход:

  1. **Напоминание за 1 день** — по событиям, наступающим не позже порога
     `event_reminder_offset_hours` (дефолт 24 ч), шлёт всем купившим билеты
     напоминание (экран `event_day_before`). Каждое событие напоминается один раз
     (claim строки в `event_notifications`, kind='day_before').

  2. **Отмена события** — администратор отменяет событие в веб-админке (ставится
     `events.canceled_at`). Веб — отдельный процесс, рассылку шлёт бот: по
     отменённым событиям без уведомления шлёт купившим экран `event_canceled` и
     помечает их билеты на ручной полный возврат (`refund_requested`, как этап 18 —
     обрабатывается менеджером в этапе 21). Один раз на событие (kind='canceled').

  3. **Уведомление о возврате** (этап 21.1) — менеджер отметил фактический возврат
     билета в веб-админке (`tickets.status='refunded'`). Бот шлёт пользователю
     «возврат произведён» (`refund_done`). При успехе — `refund_notified_at`; при
     недоставке (юзер заблокировал бота) — `refund_notify_failed` (менеджер увидит
     пометку «не доставлено» и свяжется вручную по tg-ссылке).

Защита от дублей — claim в `event_notifications` (PK event_id+kind, ON CONFLICT DO
NOTHING) для (1)/(2); для (3) — пометки на самом билете (notified/failed исключают
повторную отправку).
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone

from aiogram import Bot
import asyncpg

from .. import repo, texts
from ..config import settings
from ..logger import logger
from .events import kind_label


async def _broadcast(bot: Bot, holders: list[asyncpg.Record], text: str, tag: str) -> int:
    """Рассылает текст списку купивших. Возвращает число доставленных."""
    sent = 0
    for h in holders:
        with suppress(Exception):  # пользователь мог заблокировать бота
            await bot.send_message(h["tg_id"], text)
            sent += 1
            logger.info(
                f"🔔 {tag} → @{h['username'] or '—'} "
                f"(id:{h['tg_id']}, {h['first_name']})"
            )
    return sent


async def _send_day_before(pool: asyncpg.Pool, bot: Bot, now: datetime) -> None:
    before_ts = now + timedelta(hours=settings.event_reminder_offset_hours)
    events = await repo.events_due_day_reminder(pool, before_ts)
    for e in events:
        # Занимаем рассылку до отправки — повторный проход не задублирует.
        if not await repo.claim_event_notification(pool, e["id"], "day_before"):
            continue
        holders = await repo.paid_ticket_holders(pool, e["id"])
        text = texts.event_day_before(kind_label(e["kind"]), e["title"], e["starts_at"])
        n = await _broadcast(bot, holders, text, "Напоминание о событии")
        logger.info(
            "Напоминание за 1 день по событию #{} «{}» — отправлено {} получателям",
            e["id"], e["title"], n,
        )


async def _send_cancellations(pool: asyncpg.Pool, bot: Bot) -> None:
    events = await repo.events_pending_cancellation(pool)
    for e in events:
        if not await repo.claim_event_notification(pool, e["id"], "canceled"):
            continue
        # Помечаем билеты на ручной возврат (до рассылки — чтобы попали в админку).
        marked = await repo.mark_event_tickets_refund(pool, e["id"])
        holders = await repo.paid_ticket_holders(pool, e["id"])
        text = texts.event_canceled(kind_label(e["kind"]), e["title"], e["starts_at"])
        n = await _broadcast(bot, holders, text, "Отмена события")
        logger.info(
            "Отмена события #{} «{}» — уведомлено {} получателей, билетов на возврат {}",
            e["id"], e["title"], n, marked,
        )


async def _send_refund_notifications(pool: asyncpg.Pool, bot: Bot) -> None:
    """Уведомляет о произведённом возврате; фиксирует доставку/недоставку."""
    tickets = await repo.refunds_pending_notify(pool)
    for t in tickets:
        text = texts.refund_done(kind_label(t["kind"]), t["title"], t["starts_at"])
        try:
            await bot.send_message(t["tg_id"], text)
        except Exception as e:  # noqa: BLE001 — юзер заблокировал бота / закрыл ЛС
            await repo.mark_refund_notify_failed(pool, t["id"])
            logger.warning(
                "Уведомление о возврате билета #{} НЕ доставлено (id={}): {} — "
                "менеджеру нужна ручная связь",
                t["id"], t["tg_id"], e,
            )
            continue
        await repo.mark_refund_notified(pool, t["id"])
        logger.info(
            "🔔 Возврат произведён → id={} (билет #{}, «{}»)",
            t["tg_id"], t["id"], t["title"],
        )


async def run_event_notifications(pool: asyncpg.Pool, bot: Bot) -> None:
    """Фоновый проход: напоминания за 1 день + отменённые события + уведомления о возврате."""
    now = datetime.now(timezone.utc)
    await _send_day_before(pool, bot, now)
    await _send_cancellations(pool, bot)
    await _send_refund_notifications(pool, bot)
