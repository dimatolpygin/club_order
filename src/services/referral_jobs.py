"""Отложенное начисление реферальных бонусов (этап 17).

APScheduler-джоб: после даты бани начисляет пригласившему бонус по квалифицированным
связям. Анти-возврат: бонус положен, только если билет приглашённого всё ещё оплачен
(repo.referrals_due_for_accrual это проверяет). Начисление идемпотентно (уникальный
индекс по referral_id в bonus_ledger) — повторный проход не задвоит бонус.
"""
from __future__ import annotations

import asyncpg
from aiogram import Bot

from .. import repo
from ..logger import logger


async def run_referral_accrual(pool: asyncpg.Pool, bot: Bot) -> None:
    """Начисляет бонусы по связям, у которых дата события прошла. Уведомляет пригласивших."""
    due = await repo.referrals_due_for_accrual(pool)
    for r in due:
        ref = await repo.accrue_referral_bonus(pool, r["id"])
        if ref is None:
            continue  # уже начислено/изменилось параллельно
        bonus = int(r["bonus_amount"] or 0)
        logger.info(
            f"💰 Реф-бонус начислен: пригласившему id={r['referrer_tg_id']} +{bonus} ₽ "
            f"за «{r['title']}» (связь #{r['id']})"
        )
        try:
            await bot.send_message(
                r["referrer_tg_id"],
                f"<b>Тебе начислены бонусы</b>\n\n"
                f"Друг, которого ты пригласил, сходил на «{r['title']}». "
                f"Тебе начислено <b>{bonus} ₽</b> бонусами — можно потратить на билет "
                f"на баню (до 50% стоимости).",
            )
        except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
            logger.warning(f"Не удалось уведомить о реф-бонусе id={r['referrer_tg_id']}: {e}")
