"""Сбор всех роутеров."""
from aiogram import Router

from . import admin, navigation, start, tariffs


def get_main_router() -> Router:
    router = Router()
    # Админские команды — первыми (специфичные фильтры).
    router.include_router(admin.router)
    router.include_router(start.router)
    router.include_router(tariffs.router)
    router.include_router(navigation.router)
    return router
