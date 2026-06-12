"""Middleware сквозного логирования действий пользователей (обязательно по правилам проекта).

Логирует каждое входящее сообщение, команду и нажатие inline-кнопки:
дата/время (через Loguru), username, user_id, first_name, текст.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from .logger import logger


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update: Update = event  # type: ignore[assignment]

        if update.message is not None:
            self._log_message(update.message)
        elif update.callback_query is not None:
            self._log_callback(update.callback_query)
        elif update.chat_join_request is not None:
            self._log_join_request(update.chat_join_request)

        return await handler(event, data)

    @staticmethod
    def _log_message(msg: Message) -> None:
        u = msg.from_user
        if u is None:
            return
        text = msg.text or "(медиа)"
        logger.info(f"👤 @{u.username or '—'} (id:{u.id}, {u.first_name}) → {text}")

    @staticmethod
    def _log_callback(cb: CallbackQuery) -> None:
        u = cb.from_user
        logger.info(
            f"👤 @{u.username or '—'} (id:{u.id}, {u.first_name}) → [кнопка] {cb.data}"
        )

    @staticmethod
    def _log_join_request(req) -> None:
        u = req.from_user
        logger.info(
            f"👤 @{u.username or '—'} (id:{u.id}, {u.first_name}) → [заявка в чат {req.chat.id}]"
        )
