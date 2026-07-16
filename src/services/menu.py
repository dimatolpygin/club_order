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
    "promo": ("Ввести промокод", kb.NAV_PROMO),
    "events": ("Мероприятия", kb.NAV_EVENTS),
    "mytickets": ("Мои билеты", kb.NAV_MYTICKETS),
    "aboutmenu": ("О клубе", kb.NAV_ABOUTMENU),
    "referral": ("Пригласить друга", kb.NAV_REFERRAL),
    "about": ("Что внутри клуба", kb.NAV_ABOUT),
    "rules": ("Правила клуба", kb.NAV_RULES),
    "support": ("Поддержка", kb.NAV_SUPPORT),
}

# Контекстные раскладки верхнего уровня (этап 31): показываем только релевантное
# статусу подписки, главное действие — первым рядом во всю ширину (иерархия позицией,
# без эмодзи). Инфо/рефералка спрятаны в подменю «О клубе» (aboutmenu). Промокода на
# верхнем уровне нет — ввод остаётся в флоу оплаты/тарифа.
# Управление подпиской — ОДИН раздел: гость видит «Вступить», подписчик — «Моя подписка»
# (продление живёт ВНУТРИ этого экрана, не дублируется на верхнем уровне).
LAYOUT_GUEST: list[list[str]] = [
    ["join"], ["events", "mytickets"], ["aboutmenu", "support"],
]
LAYOUT_SUB: list[list[str]] = [
    ["mysub"], ["events", "mytickets"], ["aboutmenu", "support"],
]
# Подменю «О клубе» (открывается по кнопке aboutmenu).
ABOUTMENU_LAYOUT: list[list[str]] = [
    ["about"], ["rules"], ["referral"],
]


def _top_layout(subscribed: bool) -> list[list[str]]:
    """Раскладка верхнего уровня по статусу подписки."""
    return LAYOUT_SUB if subscribed else LAYOUT_GUEST


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


async def welcome_kb(pool: asyncpg.Pool, subscribed: bool) -> InlineKeyboardMarkup:
    """Клавиатура стартового экрана (/start и /menu): контекстна по статусу (этап 31).

    Отдельного экрана «Главное меню» больше нет (этап 38) — /menu и кнопки
    «В главное меню» ведут на этот же стартовый экран.
    """
    return _build(_top_layout(subscribed), await resolve_config(pool))


async def aboutmenu_kb(pool: asyncpg.Pool) -> InlineKeyboardMarkup:
    """Подменю «О клубе»: инфо-экраны + рефералка + «Назад» в меню (этап 31)."""
    b = InlineKeyboardBuilder()
    config = await resolve_config(pool)
    for row in ABOUTMENU_LAYOUT:
        visible = [k for k in row if config[k]["is_visible"]]
        if not visible:
            continue
        b.row(*[
            InlineKeyboardButton(text=config[k]["label"], callback_data=BUTTON_DEFS[k][1])
            for k in visible
        ])
    b.row(InlineKeyboardButton(text="Назад", callback_data=kb.NAV_START))
    return b.as_markup()


async def button_list(pool: asyncpg.Pool) -> list[dict]:
    """Список кнопок для формы веб-админки (в порядке реестра)."""
    config = await resolve_config(pool)
    return [{"key": key, **config[key]} for key in BUTTON_DEFS]


# Раскладки по имени экрана — для редактора подписей кнопок в админке (этап 22).
# Верхний уровень контекстен по статусу (этап 31), поэтому для редактора берём ОБЪЕДИНЕНИЕ
# ключей гостя и подписчика (подписи общие по ключу — правятся независимо от показа).
_TOP_UNION: list[list[str]] = [
    ["join"], ["mysub"], ["events", "mytickets"], ["aboutmenu", "support"],
]
LAYOUTS: dict[str, list[list[str]]] = {
    "welcome": _TOP_UNION,
    "aboutmenu": ABOUTMENU_LAYOUT,
}


def layout_keys(name: str) -> list[str]:
    """Плоский список ключей кнопок раскладки в порядке показа."""
    return [k for row in LAYOUTS.get(name, []) for k in row]


async def buttons_for_layout(pool: asyncpg.Pool, name: str) -> list[dict]:
    """Кнопки конкретного экрана (для редактора кнопок на странице экрана, этап 22)."""
    config = await resolve_config(pool)
    return [{"key": key, **config[key]} for key in layout_keys(name)]
