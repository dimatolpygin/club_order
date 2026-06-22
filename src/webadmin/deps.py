"""Общие зависимости веб-админки: шаблоны и проверка авторизации.

Вынесено отдельно, чтобы и app.py, и роутеры разделов (events и т.д.)
переиспользовали один объект templates и одну проверку входа без циклических
импортов.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


class NotAuthenticated(Exception):
    """Бросается, когда страница требует входа, а сессии нет."""


def current_admin(request: Request) -> dict:
    """Текущий вошедший админ из сессии или NotAuthenticated → редирект на /login."""
    admin = request.session.get("admin")
    if not admin:
        raise NotAuthenticated()
    return admin
