"""Реестр редактируемых экранов бота + резолв текста с учётом БД (этап 22).

Тексты инфо-экранов бота правятся из веб-админки без правки кода. Состав экранов
и дефолтные тексты — здесь, это источник истины (дефолты ссылаются на `texts.py`).
Переопределения текста хранятся в таблице `screen_texts` (через repo); бот сливает
реестр с переопределениями при каждом рендере экрана, поэтому правки применяются
без рестарта — ровно как `services.menu` для кнопок (этап 19).

Редактируемы только СТАТИЧНЫЕ инфо-экраны (без динамических вставок — цен, дат,
списков). Динамические экраны (тарифы, оплата, карточки событий) собираются из
данных и здесь не значатся: правка их «обрамления» рискует сломать подстановку.

`menu` у экрана связывает его с раскладкой кнопок из `services.menu` (этап 19) —
на странице такого экрана в админке правится и текст, и подписи/видимость его
кнопок (объединение с этапом 19). У инфо-экранов без меню кнопки навигационные
(хардкод в `keyboards.py`) и тут не редактируются.
"""
from __future__ import annotations

import asyncpg

from .. import repo, texts

# Реестр: ключ → метаданные экрана. Порядок определяет порядок в админке.
#   title   — человекочитаемое имя экрана в админке;
#   default — дефолтный текст (источник — texts.py);
#   menu    — связанная раскладка кнопок ('welcome'/'main') или None;
#   hint    — короткая подсказка для админки.
SCREEN_DEFS: dict[str, dict] = {
    "start": {
        "title": "Приветствие (/start)",
        "default": texts.WELCOME,
        "menu": "welcome",
        "hint": "Первый экран при входе в бота.",
    },
    "menu": {
        "title": "Главное меню (/menu)",
        "default": texts.MAIN_MENU,
        "menu": "main",
        "hint": "Главное меню бота.",
    },
    "aboutmenu": {
        "title": "Подменю «О клубе»",
        "default": texts.ABOUTMENU,
        "menu": "aboutmenu",
        "hint": "Хаб: Что внутри · Правила · Пригласить друга. Подписи кнопок правятся здесь.",
    },
    "about": {
        "title": "Что внутри клуба",
        "default": texts.ABOUT,
        "menu": None,
        "hint": "Описание клуба. Кнопки экрана — навигационные, не редактируются.",
    },
    "rules": {
        "title": "Правила участия",
        "default": texts.RULES,
        "menu": None,
        "hint": "Правила пространства. Кнопки экрана — навигационные, не редактируются.",
    },
    "support": {
        "title": "Поддержка",
        "default": texts.SUPPORT,
        "menu": None,
        "hint": "Экран поддержки (когда ссылка задана). Сама ссылка — в настройках бота.",
    },
    "support_no_link": {
        "title": "Поддержка — ссылка не задана",
        "default": texts.SUPPORT_NO_LINK,
        "menu": None,
        "hint": "Запасной текст, если контакт поддержки ещё не настроен.",
    },
}


def default_text(key: str) -> str:
    """Дефолтный текст экрана из реестра (источник — texts.py)."""
    return SCREEN_DEFS[key]["default"]


async def text(pool: asyncpg.Pool, key: str) -> str:
    """Текст экрана: переопределение из БД или дефолт из реестра (fallback).

    Неизвестный ключ → дефолт недоступен, поднимаем KeyError (ошибка в коде).
    """
    overrides = await repo.get_screen_overrides(pool)
    return overrides.get(key) or SCREEN_DEFS[key]["default"]


async def screen_list(pool: asyncpg.Pool) -> list[dict]:
    """Список экранов для админки (в порядке реестра): ключ, имя, текущий текст, кастом."""
    overrides = await repo.get_screen_overrides(pool)
    result: list[dict] = []
    for key, meta in SCREEN_DEFS.items():
        custom = key in overrides
        result.append({
            "key": key,
            "title": meta["title"],
            "hint": meta["hint"],
            "menu": meta["menu"],
            "body": overrides.get(key) or meta["default"],
            "default_body": meta["default"],
            "custom": custom,
        })
    return result


async def screen_one(pool: asyncpg.Pool, key: str) -> dict | None:
    """Один экран для формы админки (или None, если ключ неизвестен)."""
    if key not in SCREEN_DEFS:
        return None
    for screen in await screen_list(pool):
        if screen["key"] == key:
            return screen
    return None
