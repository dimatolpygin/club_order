"""Отложенное начисление реферальных бонусов (этап 17).

APScheduler-джоб: после даты бани начисляет пригласившему бонус по квалифицированным
связям. Анти-возврат: бонус положен, только если билет приглашённого всё ещё оплачен
(repo.referrals_due_for_accrual это проверяет). Начисление идемпотентно (уникальный
индекс по referral_id в bonus_ledger) — повторный проход не задвоит бонус.
"""
from __future__ import annotations

import asyncpg
from aiogram import Bot

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger


async def run_referral_accrual(pool: asyncpg.Pool, bot: Bot) -> None:
    """Начисляет бонусы по связям, у которых наступил момент начисления.

    С этапа 40 момент берётся из `referrals.accrue_after`: для билетов это дата
    события (как было), для покупок без даты — момент оплаты. Последние обычно уже
    начислены сразу (services.referral_notify), но джоб остаётся подстраховкой —
    начисление идемпотентно.
    """
    due = await repo.referrals_due_for_accrual(pool)
    for r in due:
        ref = await repo.accrue_referral_bonus(pool, r["id"])
        if ref is None:
            continue  # уже начислено/изменилось параллельно
        bonus = int(r["bonus_amount"] or 0)
        # title есть только у связей, квалифицированных билетом (LEFT JOIN events).
        title = r["title"]
        logger.info(
            f"💰 Реф-бонус начислен: пригласившему id={r['referrer_tg_id']} +{bonus} ₽ "
            f"за «{title or r['category'] or 'покупку'}» (связь #{r['id']})"
        )
        if bonus <= 0:
            continue
        try:
            await bot.send_message(
                r["referrer_tg_id"],
                texts.referral_bonus_accrued(title, bonus),
                # Кнопки «Мои бонусы» · «Главное меню» (этап 41) — сообщение не тупик.
                reply_markup=kb.bonus_accrued_kb(),
            )
        except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
            logger.warning(f"Не удалось уведомить о реф-бонусе id={r['referrer_tg_id']}: {e}")
