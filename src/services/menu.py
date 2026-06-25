"""Реестр кнопок меню бота + сборка клавиатур с учётом настроек (этап 19).

Структура и раскладка меню (какие кнопки, в каком порядке, по сколько в ряд) —
здесь, это источник истины. Текст и видимость каждой кнопки можно переопределить
из веб-админки (таблица `menu_buttons`); бот сливает реестр с переопределениями
при каждом рендере, поэтому правки применяются без рестарта.

Кнопка определяется ключом (`join`, `events`, …). Раскладка — список рядов, ряд —
список ключей (1–2 кнопки). Скрытая кнопка выпадает из ряда; опустевший ряд
пропускается; одиночная видимая кнопка из пары занимает ряд целиком.
"""
from __future__ import annotations

import asyncpg
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import keyboards as kb
from .. import repo

# Реестр: ключ → (дефолтная подпись, callback). Порядок определяет порядок в админке.
BUTTON_DEFS: dict[str, tuple[str, str]] = {
    "join": ("Вступить в клуб", kb.NAV_JOIN),
    "mysub": ("Моя подписка", kb.NAV_MYSUB),
    "renew": ("Продлить", kb.NAV_RENEW),
    "promo": ("Ввести промокод", kb.NAV_PROMO),
    "events": ("Мероприятия", kb.NAV_EVENTS),
    "mytickets": ("Мои билеты", kb.NAV_MYTICKETS),
    "referral": ("Пригласить друга", kb.NAV_REFERRAL),
    "about": ("Что внутри клуба", kb.NAV_ABOUT),
    "rules": ("Правила клуба", kb.NAV_RULES),
    "support": ("Поддержка", kb.NAV_SUPPORT),
}

# Раскладки меню (ряды по 1–2 ключа).
WELCOME_LAYOUT: list[list[str]] = [
    ["join"], ["events", "mytickets"], ["about"], ["rules"], ["support"],
]
MAIN_LAYOUT: list[list[str]] = [
    ["join"], ["mysub", "renew"], ["promo"], ["events", "mytickets"],
    ["referral"], ["about", "rules"], ["support"],
]


async def resolve_config(pool: asyncpg.Pool) -> dict[str, dict]:
    """Слитый конфиг кнопок: реестр + переопределения из БД.

    Возвращает {key: {'label': str, 'is_visible': bool, 'default_label': str,
    'custom': bool}} для всех кнопок реестра.
    """
    overrides = await repo.get_menu_overrides(pool)
    config: dict[str, dict] = {}
    for key, (default_label, _cb) in BUTTON_DEFS.items():
        ov = overrides.get(key)
        custom_label = ov["label"] if ov and ov["label"] else None
        config[key] = {
            "label": custom_label or default_label,
            "default_label": default_label,
            "is_visible": ov["is_visible"] if ov is not None else True,
            "custom": custom_label is not None,
        }
    return config


def _build(layout: list[list[str]], config: dict[str, dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for row in layout:
        visible = [k for k in row if config[k]["is_visible"]]
        if not visible:
            continue
        b.row(*[
            InlineKeyboardButton(text=config[k]["label"], callback_data=BUTTON_DEFS[k][1])
            for k in visible
        ])
    return b.as_markup()


async def welcome_kb(pool: asyncpg.Pool) -> InlineKeyboardMarkup:
    """Клавиатура приветствия (/start) с учётом настроек кнопок."""
    return _build(WELCOME_LAYOUT, await resolve_config(pool))


async def main_menu_kb(pool: asyncpg.Pool) -> InlineKeyboardMarkup:
    """Клавиатура главного меню (/menu) с учётом настроек кнопок."""
    return _build(MAIN_LAYOUT, await resolve_config(pool))


async def button_list(pool: asyncpg.Pool) -> list[dict]:
    """Список кнопок для формы веб-админки (в порядке реестра)."""
    config = await resolve_config(pool)
    return [{"key": key, **config[key]} for key in BUTTON_DEFS]
