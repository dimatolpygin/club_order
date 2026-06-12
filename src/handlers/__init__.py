"""Сбор всех роутеров."""
from aiogram import Router

from . import navigation, start


def get_main_router() -> Router:
    router = Router()
    router.include_router(start.router)
    router.include_router(navigation.router)
    return router
