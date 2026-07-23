"""Уведомления админам о продажах (этап 42).

Админы видят продажи в реальном времени, не заходя в веб-админку: после оплаты
билета, после оплаты/продления подписки и при выходе участника за неуплату всем
получателям уходит сообщение со сводкой.

Сводки считаются одним SQL-запросом (`repo.event_sales_summary` — по конкретному
мероприятию, решение раунда 4; `repo.club_members_summary` — по клубу, сумма =
последняя успешная оплата каждого активного подписчика, бесплатный участник = 0).

Получатели — админы из `.env` плюс добавленные в веб-админке (этап 27). Админ,
заблокировавший бота, не ломает отправку остальным; сбой уведомления никогда не
должен ронять выдачу билета/активацию подписки — вызывающий код оборачивает
вызовы в `suppress`, а здесь каждая отправка идёт под своим try.
"""
from __future__ import annotations

from aiogram import Bot
import asyncpg

from .. import repo, texts
from ..config import settings
from ..logger import logger
from ..utils import fmt_price
from . import app_settings
from . import events as ev


def all_admin_ids() -> list[int]:
    """Все получатели: админы из `.env` + добавленные из админки (без дублей)."""
    return sorted(set(settings.admin_id_list) | app_settings.extra_admin_ids())


async def notify_admins(bot: Bot, text: str) -> int:
    """Шлёт текст всем админам. Возвращает число успешно доставленных сообщений."""
    sent = 0
    for admin_id in all_admin_ids():
        try:
            await bot.send_message(admin_id, text)
            sent += 1
        except Exception as e:  # noqa: BLE001 — админ мог не начать диалог/заблокировать
            logger.warning(f"Не удалось уведомить админа id={admin_id}: {e}")
    return sent


async def _buyer(pool: asyncpg.Pool, tg_id: int) -> tuple[str | None, str | None]:
    """(username, first_name) покупателя; для удалённого профиля — (None, None)."""
    user = await repo.get_user(pool, tg_id)
    if user is None:
        return None, None
    return user["username"], user["first_name"]


async def ticket_sold(
    pool: asyncpg.Pool, bot: Bot, *, tg_id: int, ticket, event
) -> None:
    """Уведомление о проданном билете + сводка по этому мероприятию."""
    if event is None or ticket is None:
        return
    username, first_name = await _buyer(pool, tg_id)
    s = await repo.event_sales_summary(pool, event["id"])
    text = texts.admin_ticket_sale(
        username=username, first_name=first_name, user_id=tg_id,
        title=event["title"], ticket_label=ev.ticket_label(ticket["ticket_type"]),
        price=fmt_price(ticket["price"]),
        tickets=s["tickets"], people=s["people"],
        amount=fmt_price(s["amount"]), seats=s["seats"],
    )
    sent = await notify_admins(bot, text)
    logger.info(
        f"📣 Админам о продаже билета #{ticket['id']} («{event['title']}», "
        f"{fmt_price(ticket['price'])} ₽) — доставлено {sent}"
    )


async def subscription_paid(
    pool: asyncpg.Pool, bot: Bot, *, tg_id: int, payment, subscription
) -> None:
    """Уведомление об оплате/продлении подписки + сводка по клубу."""
    if subscription is None:
        return
    username, first_name = await _buyer(pool, tg_id)
    s = await repo.club_members_summary(pool)
    renewal = payment["kind"] == "renewal"
    period = texts.period_phrase(subscription["months"], subscription["unit"])
    text = texts.admin_subscription_sale(
        username=username, first_name=first_name, user_id=tg_id,
        renewal=renewal, price=fmt_price(payment["amount"]), period=period,
        members=s["members"], amount=fmt_price(s["amount"]),
    )
    sent = await notify_admins(bot, text)
    logger.info(
        f"📣 Админам о {'продлении' if renewal else 'новой подписке'} "
        f"(tg_id={tg_id}, {fmt_price(payment['amount'])} ₽) — доставлено {sent}"
    )


async def subscription_expired(pool: asyncpg.Pool, bot: Bot, *, tg_id: int) -> None:
    """Уведомление о выходе участника за неуплату + сводка по клубу.

    Вызывается ПОСЛЕ пометки подписки 'expired', поэтому сводка уже без него.
    """
    username, first_name = await _buyer(pool, tg_id)
    s = await repo.club_members_summary(pool)
    text = texts.admin_subscription_expired(
        username=username, first_name=first_name, user_id=tg_id,
        members=s["members"], amount=fmt_price(s["amount"]),
    )
    sent = await notify_admins(bot, text)
    logger.info(f"📣 Админам о выходе за неуплату (tg_id={tg_id}) — доставлено {sent}")
