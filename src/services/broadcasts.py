"""Рассылки из веб-админки (этап 26): бот-джоб разбирает очередь broadcasts.

Веб кладёт задачу в таблицу broadcasts (status='pending') с текстом и URL фото в S3;
этот джоб забирает её (claim: pending→sending), рассылает по выбранной аудитории
через бота с троттлингом, помечает заблокировавших (set_user_blocked) и проставляет
итог (status='done' + счётчики отправлено/заблокировали/ошибки). Логика отправки —
как в боте /admin (этап 8), но фото только по URL (file_id у веб-загрузки нет).
Паттерн очереди — как мост этапа 21.1.
"""
from __future__ import annotations

import asyncio
import json

import asyncpg
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InputMediaPhoto

from .. import repo
from ..logger import logger


def _media(photos: list[dict], text: str | None) -> list[InputMediaPhoto]:
    """media_group из URL; подпись — только на первом фото."""
    return [
        InputMediaPhoto(media=p["url"], caption=text if (i == 0 and text) else None)
        for i, p in enumerate(photos)
    ]


async def _send_one(bot: Bot, uid: int, text: str | None, photos: list[dict]) -> None:
    """Отправляет один экземпляр рассылки конкретному пользователю."""
    if not photos:
        await bot.send_message(uid, text)
    elif len(photos) == 1:
        await bot.send_photo(uid, photos[0]["url"], caption=text)
    else:
        await bot.send_media_group(uid, _media(photos, text))


async def _run_one(pool: asyncpg.Pool, bot: Bot, b: asyncpg.Record) -> None:
    """Рассылает одну задачу по аудитории и фиксирует итог."""
    photos = json.loads(b["photos"] or "[]")
    text = b["body"]
    user_ids = await repo.get_audience_ids(pool, b["audience"])
    await repo.set_broadcast_total(pool, b["id"], len(user_ids))
    logger.info(
        "📣 Рассылка #{} [{}] стартовала: получателей {}, фото {}",
        b["id"], b["audience"], len(user_ids), len(photos),
    )

    sent = blocked = failed = 0
    for uid in user_ids:
        try:
            await _send_one(bot, uid, text, photos)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            await repo.set_user_blocked(pool, uid, True)
        except Exception as e:  # noqa: BLE001 — прочие ошибки доставки не валят рассылку
            failed += 1
            logger.warning("Рассылка #{}: не доставлено id={}: {}", b["id"], uid, e)
        # Альбом = несколько сообщений — шлём чуть медленнее (лимиты Telegram).
        await asyncio.sleep(0.1 if photos else 0.05)

    await repo.finish_broadcast(pool, b["id"], sent=sent, blocked=blocked, failed=failed)
    logger.info(
        "📣 Рассылка #{} завершена: отправлено {}, заблок. {}, ошибок {}",
        b["id"], sent, blocked, failed,
    )


async def run_broadcast_queue(pool: asyncpg.Pool, bot: Bot) -> None:
    """Фоновый проход: разбирает все ожидающие рассылки (по одной, по очереди)."""
    while True:
        b = await repo.claim_pending_broadcast(pool)
        if b is None:
            return
        try:
            await _run_one(pool, bot, b)
        except Exception as e:  # noqa: BLE001 — задача не должна валить джоб
            logger.error("Рассылка #{}: проход упал: {}", b["id"], e)
            await repo.finish_broadcast(pool, b["id"], sent=0, blocked=0, failed=0)
