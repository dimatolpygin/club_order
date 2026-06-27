"""Изолированный smoke-тест безопасного показа экрана с картинкой (этап 37).

Проверяет services.screens.render без Telegram/БД на фейковом сообщении: что для всех
4 комбинаций (цель с фото/без × текущее сообщение фото/текст) и для нового сообщения
(/start, /menu) вызывается правильный метод и переходы экран-с-фото ↔ экран-без-фото
не ломаются (delete + пересоздание там, где edit невозможен). Запуск:
python -m tests.test_screen_view
"""
from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto

from src.services import screens


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


class FakeMessage:
    """Сообщение-заглушка: запоминает вызванные методы; edit_media умеет «падать»."""

    def __init__(self, *, is_photo: bool, edit_media_fails: bool = False) -> None:
        self.photo = [object()] if is_photo else None
        self._edit_media_fails = edit_media_fails
        self.calls: list[str] = []

    async def answer(self, text, reply_markup=None):
        self.calls.append("answer")

    async def answer_photo(self, photo, caption=None, reply_markup=None):
        self.calls.append("answer_photo")

    async def edit_text(self, text, reply_markup=None):
        self.calls.append("edit_text")

    async def edit_media(self, media, reply_markup=None):
        assert isinstance(media, InputMediaPhoto)
        if self._edit_media_fails:
            raise TelegramBadRequest(method=None, message="not modified")
        self.calls.append("edit_media")

    async def delete(self):
        self.calls.append("delete")


async def _render(msg, *, photo_url, edit):
    await screens.render(msg, text="t", markup=None, photo_url=photo_url, edit=edit)
    return msg.calls


def main() -> None:
    run = asyncio.run

    # /start, /menu (новое сообщение): фото → answer_photo, без фото → answer.
    check("new msg, без фото → answer",
          run(_render(FakeMessage(is_photo=False), photo_url=None, edit=False)), ["answer"])
    check("new msg, с фото → answer_photo",
          run(_render(FakeMessage(is_photo=False), photo_url="u", edit=False)), ["answer_photo"])

    # Переход по кнопке (edit=True) — 4 комбинации.
    check("edit: цель без фото, текущее текст → edit_text (без регресса)",
          run(_render(FakeMessage(is_photo=False), photo_url=None, edit=True)), ["edit_text"])
    check("edit: цель без фото, текущее фото → delete + answer",
          run(_render(FakeMessage(is_photo=True), photo_url=None, edit=True)), ["delete", "answer"])
    check("edit: цель с фото, текущее фото → edit_media",
          run(_render(FakeMessage(is_photo=True), photo_url="u", edit=True)), ["edit_media"])
    check("edit: цель с фото, текущее текст → delete + answer_photo",
          run(_render(FakeMessage(is_photo=False), photo_url="u", edit=True)), ["delete", "answer_photo"])

    # edit_media упал (not modified) → пересоздаём фото: delete + answer_photo.
    check("edit: цель с фото, текущее фото, edit_media падает → delete + answer_photo",
          run(_render(FakeMessage(is_photo=True, edit_media_fails=True), photo_url="u", edit=True)),
          ["delete", "answer_photo"])

    # CAPTION_LIMIT — закреплён лимит подписи Telegram (валидация в админке от него).
    check("лимит подписи = 1024", screens.CAPTION_LIMIT, 1024)

    print("\nВсе проверки безопасного показа экрана пройдены.")


if __name__ == "__main__":
    main()
