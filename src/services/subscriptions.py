"""Жизненный цикл подписок: фоновая проверка окончаний (этап 5).

Джоб APScheduler помечает истёкшие подписки 'expired', кикает пользователя из
закрытой группы и шлёт уведомление «подписка закончилась». Кик = ban + unban,
чтобы место освободилось, но пользователь мог вернуться после новой оплаты
(подаст заявку заново → этап 4 одобрит её при активной подписке).
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..config import settings
from ..logger import logger
from . import admin_alerts


async def kick_from_group(bot: Bot, tg_id: int, reason: str = "подписка истекла") -> None:
    """Удаляет пользователя из группы с возможностью повторного вступления.

    Используется и фоновой проверкой окончаний, и ручным аннулированием из админки.
    """
    club_id = settings.club_chat_id_int
    if club_id is None:
        return
    try:
        await bot.ban_chat_member(club_id, tg_id)
        # Сразу снимаем бан — это «кик»: убрали из чата, но вход не запрещён навсегда.
        await bot.unban_chat_member(club_id, tg_id)
        logger.info(f"👢 Кик из группы: tg_id={tg_id} ({reason})")
    except Exception as e:  # noqa: BLE001 — мог уже выйти / бот не админ
        logger.warning(f"Не удалось кикнуть tg_id={tg_id} из группы: {e}")


async def _notify_ended(bot: Bot, tg_id: int) -> None:
    with suppress(Exception):  # пользователь мог заблокировать бота
        await bot.send_message(tg_id, texts.SUB_ENDED, reply_markup=kb.sub_ended_kb())


async def run_expiry_check(pool: asyncpg.Pool, bot: Bot) -> None:
    """Фоновый проход: пометить истёкшие подписки, кикнуть и уведомить юзеров."""
    expired = await repo.expire_due_subscriptions(pool)
    if not expired:
        return
    logger.info(f"⏰ Проверка окончаний: истекло подписок — {len(expired)}")
    for row in expired:
        tg_id = row["tg_id"]
        try:
            await kick_from_group(bot, tg_id)
            await _notify_ended(bot, tg_id)
            # Уведомление админам о выходе за неуплату (этап 42). Подписка уже
            # помечена 'expired' — сводка по клубу считается без выбывшего.
            with suppress(Exception):
                await admin_alerts.subscription_expired(pool, bot, tg_id=tg_id)
            logger.info(f"🔚 Подписка #{row['id']} завершена (tg_id={tg_id})")
        except Exception as e:  # noqa: BLE001 — один юзер не должен ронять цикл
            logger.error(f"Проверка окончаний: ошибка по tg_id={tg_id}: {e}")
