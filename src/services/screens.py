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

from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, Message
import asyncpg

from .. import repo, texts

# Лимит подписи под фото в Telegram. Экран с картинкой показывается ОДНИМ
# сообщением (фото + подпись), поэтому его текст не может быть длиннее.
CAPTION_LIMIT = 1024

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
        "hint": "Первый экран при входе в бота (он же /menu — отдельного меню нет).",
    },
    "aboutmenu": {
        "title": "Подменю «О клубе»",
        "default": texts.ABOUTMENU,
        "menu": "aboutmenu",
        "hint": "Хаб: Что внутри · Правила. Подписи кнопок правятся здесь.",
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
    "yoga": {
        "title": "Йога — описание раздела",
        "default": texts.YOGA_INTRO,
        "menu": None,
        "hint": "Вводный текст раздела «Йога». Форматы и цены — кнопками (раздел «Йога» в админке).",
    },
    "consult": {
        "title": "Консультации — описание раздела",
        "default": texts.CONSULT_INTRO,
        "menu": None,
        "hint": "Вводный текст раздела «Консультации». Пакеты и цены — кнопками (раздел «Консультации» в админке).",
    },
    "pd_consent": {
        "title": "Согласие на обработку ПД (152-ФЗ)",
        "default": texts.PD_CONSENT,
        "menu": None,
        "docs": True,
        "hint": "Текст «Политики» + согласие при первом входе. Сюда вставляется финальный "
                "текст заказчика. Можно приложить документы (оферта, политика и т.п.) — бот "
                "пришлёт их файлами перед текстом. Кнопка «Согласен» добавляется ботом.",
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


def supports_docs(key: str) -> bool:
    """Можно ли прикладывать документы к экрану (оферта/политика и т.п.)."""
    return bool(SCREEN_DEFS.get(key, {}).get("docs"))


async def text(pool: asyncpg.Pool, key: str) -> str:
    """Текст экрана: переопределение из БД или дефолт из реестра (fallback).

    Неизвестный ключ → дефолт недоступен, поднимаем KeyError (ошибка в коде).
    """
    ov = (await repo.get_screen_overrides(pool)).get(key) or {}
    return ov.get("body") or SCREEN_DEFS[key]["default"]


async def resolve(pool: asyncpg.Pool, key: str) -> dict:
    """Что показать на экране: {"text": ..., "photo_url": str|None}.

    Единая точка резолва для бота: текст (переопределение или дефолт) + картинка
    (None = без фото). Используется хендлерами вместе с render().
    """
    ov = (await repo.get_screen_overrides(pool)).get(key) or {}
    return {
        "text": ov.get("body") or SCREEN_DEFS[key]["default"],
        "photo_url": ov.get("photo_url"),
        "documents": ov.get("documents") or [],
    }


async def screen_list(pool: asyncpg.Pool) -> list[dict]:
    """Список экранов для админки (в порядке реестра): ключ, имя, текст, фото, кастом."""
    overrides = await repo.get_screen_overrides(pool)
    result: list[dict] = []
    for key, meta in SCREEN_DEFS.items():
        ov = overrides.get(key) or {}
        result.append({
            "key": key,
            "title": meta["title"],
            "hint": meta["hint"],
            "menu": meta["menu"],
            "body": ov.get("body") or meta["default"],
            "default_body": meta["default"],
            "custom": bool(ov.get("body")),
            "photo_url": ov.get("photo_url"),
            "docs_enabled": bool(meta.get("docs")),
            "documents": ov.get("documents") or [],
        })
    return result


async def render(
    message: Message,
    *,
    text: str,
    markup: InlineKeyboardMarkup,
    photo_url: str | None,
    edit: bool,
) -> None:
    """Безопасный показ инфо-экрана (с фото или без), не ломающий навигацию.

    Telegram не умеет edit_text по сообщению-фото и не превращает текст в фото через
    edit, поэтому переход между экраном-с-фото и экраном-без-фото нельзя делать наивно.
    Единое правило для ВСЕХ точек показа (навигация по кнопкам и /start, /menu):

    - edit=False (/start, /menu — новое сообщение): answer_photo если фото, иначе answer.
    - edit=True (переход по кнопке — заменяем текущее сообщение):
      * цель без фото, текущее текстовое → edit_text (как раньше, плавно, без регресса);
      * цель без фото, текущее фото       → delete + send_message;
      * цель с фото,  текущее фото        → edit_media (на ошибку → delete + send_photo);
      * цель с фото,  текущее текстовое   → delete + send_photo.

    Все delete/edit под suppress: устаревшее/удалённое сообщение не валит флоу.
    """
    if not edit:
        if photo_url:
            await message.answer_photo(photo_url, caption=text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)
        return

    current_is_photo = bool(message.photo)

    if not photo_url:
        if current_is_photo:
            with suppress(TelegramBadRequest):
                await message.delete()
            await message.answer(text, reply_markup=markup)
        else:
            with suppress(TelegramBadRequest):  # «message is not modified» — не критично
                await message.edit_text(text, reply_markup=markup)
        return

    # Целевой экран с фото.
    if current_is_photo:
        try:
            await message.edit_media(
                InputMediaPhoto(media=photo_url, caption=text), reply_markup=markup,
            )
        except TelegramBadRequest:  # not modified / иная ошибка edit — пересоздаём
            with suppress(TelegramBadRequest):
                await message.delete()
            await message.answer_photo(photo_url, caption=text, reply_markup=markup)
    else:
        with suppress(TelegramBadRequest):
            await message.delete()
        await message.answer_photo(photo_url, caption=text, reply_markup=markup)


async def screen_one(pool: asyncpg.Pool, key: str) -> dict | None:
    """Один экран для формы админки (или None, если ключ неизвестен)."""
    if key not in SCREEN_DEFS:
        return None
    for screen in await screen_list(pool):
        if screen["key"] == key:
            return screen
    return None
