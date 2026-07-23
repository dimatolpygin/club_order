"""Квалификация реф-связи после оплаты + уведомление пригласившему (этап 40).

Единая точка для ВСЕХ категорий покупок (билеты, подписка, йога, консультации):
считает бонус по правилу категории, фиксирует связь и сообщает пригласившему.

Момент начисления:
  · билет (баня/ретрит) — бонус ждёт даты события, начислит джоб
    (`referral_jobs.run_referral_accrual`); пригласившему сразу пишем «начислим
    ХХХ бонусов после ДД.ММ»;
  · подписка/йога/консультации — даты нет, поэтому бонус начисляем ПРЯМО ЗДЕСЬ
    (тем же идемпотентным `repo.accrue_referral_bonus`) и пишем «начислено».

Вынесено отдельным модулем, чтобы не плодить дубли в tickets/payments и не
создавать циклический импорт между ними.
"""
from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from aiogram import Bot

from .. import repo, texts
from ..logger import logger
from . import referral_rules as ref_rules


async def qualify_and_notify(
    pool: asyncpg.Pool,
    bot: Bot,
    *,
    invitee_tg_id: int,
    category: str,
    purchase_title: str,
    paid_amount,
    event_id: int | None = None,
    event_starts_at: datetime | None = None,
) -> None:
    """Квалифицирует связь приглашённого и уведомляет пригласившего.

    Идемпотентно: `repo.qualify_referral` трогает только связь в статусе 'pending',
    поэтому повторный вызов (ретрай поллера платежей) ничего не задваивает.
    Суммы фиксируются на момент покупки — последующая правка правил не влияет.
    `paid_amount` — сумма покупки друга (база для процентных правил).
    """
    rule = await repo.get_referral_rule(pool, category)
    bonus = ref_rules.bonus_for(rule, paid_amount)
    # Информационная величина скидки новичка (показывается в цепочках админки).
    discount = ref_rules.discount_for(rule, paid_amount)
    instant = ref_rules.is_instant(category)
    accrue_after = datetime.now(timezone.utc) if instant else event_starts_at

    row = await repo.qualify_referral(
        pool,
        invitee_tg_id=invitee_tg_id,
        event_id=event_id,
        discount_amount=discount,
        bonus_amount=bonus,
        category=category,
        accrue_after=accrue_after,
    )
    if row is None:
        return  # связи нет или она уже квалифицирована

    referrer = row["referrer_tg_id"]
    logger.info(
        f"🔗 Реферал квалифицирован: invitee={invitee_tg_id}, категория «{category}», "
        f"бонус {bonus} ₽ пригласившему id={referrer} "
        f"({'сразу' if instant else f'после {event_starts_at:%d.%m.%Y}'})"
    )

    # Покупки без даты — начисляем немедленно, чтобы бонус был доступен сразу.
    if instant and bonus > 0:
        accrued = await repo.accrue_referral_bonus(pool, row["id"])
        if accrued is not None:
            logger.info(f"💰 Реф-бонус начислен сразу: id={referrer} +{bonus} ₽")

    text = texts.referral_friend_purchased(
        purchase_title, bonus, accrue_at=None if instant else event_starts_at
    )
    try:
        await bot.send_message(referrer, text)
    except Exception as e:  # noqa: BLE001 — пригласивший мог заблокировать бота
        logger.warning(f"Не удалось уведомить пригласившего id={referrer}: {e}")
