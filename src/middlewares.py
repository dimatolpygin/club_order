"""Middleware сквозного логирования действий пользователей (обязательно по правилам проекта).

Логирует каждое входящее сообщение, команду и нажатие inline-кнопки:
дата/время (через Loguru), username, user_id, first_name, текст. Параллельно
пишет действие в журнал user_events (repo.add_event) — чтобы в админке смотреть
«путь» конкретного пользователя (что и в каком порядке он нажимал).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from . import repo
from .logger import logger

# Человеческие подписи кнопок (callback_data) для журнала действий.
_CB_LABELS = {
    "nav:start": "Открыл главный экран",
    "nav:about": "Открыл «Что внутри клуба»",
    "nav:rules": "Открыл «Правила»",
    "nav:support": "Открыл «Поддержка»",
    "nav:menu": "Открыл «Главное меню»",
    "nav:join": "Нажал «Вступить в клуб»",
    "nav:tariff": "Открыл выбор тарифа",
    "nav:mysub": "Открыл «Моя подписка»",
    "nav:renew": "Нажал «Продлить»",
    "nav:promo": "Нажал «Ввести промокод»",
}

# Подписи по префиксу для динамических callback (с id в хвосте).
_CB_PREFIXES = (
    ("buy:", "Выбрал срок подписки"),
    ("promo:buy:", "Оплата по промокоду"),
    ("pay:create:", "Перешёл к оплате"),
    ("pay:check:", "Нажал «Проверить оплату»"),
    ("renew:", "Выбрал срок продления"),
    ("adm:", "Админка"),
)


def describe_callback(data: str | None) -> str:
    if not data:
        return "Кнопка"
    if data in _CB_LABELS:
        return _CB_LABELS[data]
    for prefix, label in _CB_PREFIXES:
        if data.startswith(prefix):
            return label
    return f"Кнопка: {data}"


def describe_message(msg: Message) -> str:
    text = msg.text
    if not text:
        return "Прислал медиа"
    if text.startswith("/"):
        return f"Команда {text.split()[0]}"
    short = text if len(text) <= 40 else text[:40] + "…"
    return f"Написал: {short}"


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update: Update = event  # type: ignore[assignment]

        user = None
        label: str | None = None
        if update.message is not None:
            self._log_message(update.message)
            user = update.message.from_user
            label = describe_message(update.message)
        elif update.callback_query is not None:
            self._log_callback(update.callback_query)
            user = update.callback_query.from_user
            label = describe_callback(update.callback_query.data)
        elif update.chat_join_request is not None:
            self._log_join_request(update.chat_join_request)
            user = update.chat_join_request.from_user
            label = "Заявка на вступление в чат"

        pool = data.get("pool")
        if pool is not None and user is not None and label is not None:
            try:
                await repo.add_event(pool, user.id, label)
            except Exception as e:  # noqa: BLE001 — журнал не должен ронять обработку
                logger.warning(f"Не удалось записать событие истории: {e!r}")

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
