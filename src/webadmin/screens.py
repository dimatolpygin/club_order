"""Раздел админки «Экраны бота» (этап 22).

Правка текстов инфо-экранов бота (приветствие, главное меню, что внутри, правила,
поддержка) без правки кода. Состав экранов и дефолтные тексты — в реестре
services.screens; здесь правится только текст (таблица screen_texts через repo).
На странице экрана с меню (приветствие/главное меню) объединён редактор подписей и
видимости его кнопок (объединение с этапом 19 — таблица menu_buttons). Бот применяет
правки на лету.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..db import get_pool
from ..logger import logger
from ..services import menu, screens
from .deps import current_admin, templates

router = APIRouter()


@router.get("/screens")
async def screens_page(request: Request, ok: int = 0):
    current_admin(request)
    pool = get_pool()
    items = await screens.screen_list(pool)
    return templates.TemplateResponse(
        request, "screens_list.html",
        {
            "active": "screens", "admin": request.session.get("admin"),
            "screens": items, "ok": bool(ok),
        },
    )


@router.get("/screens/{key}")
async def screen_form(request: Request, key: str, ok: int = 0):
    current_admin(request)
    pool = get_pool()
    screen = await screens.screen_one(pool, key)
    if screen is None:
        return RedirectResponse("/screens", status_code=303)
    buttons = (
        await menu.buttons_for_layout(pool, screen["menu"]) if screen["menu"] else []
    )
    return templates.TemplateResponse(
        request, "screen_form.html",
        {
            "active": "screens", "admin": request.session.get("admin"),
            "screen": screen, "buttons": buttons, "ok": bool(ok),
        },
    )


@router.post("/screens/{key}")
async def screen_save(request: Request, key: str):
    current_admin(request)
    pool = get_pool()
    screen = await screens.screen_one(pool, key)
    if screen is None:
        return RedirectResponse("/screens", status_code=303)
    form = await request.form()

    # Текст: пустой или совпал с дефолтом → храним NULL (дефолт из реестра).
    raw = (form.get("body") or "").replace("\r\n", "\n").strip()
    default = screens.default_text(key).strip()
    body = None if (not raw or raw == default) else raw
    await repo.upsert_screen_text(pool, key, body)

    # Кнопки экрана (только для меню-экранов) — переопределения подписи/видимости.
    if screen["menu"]:
        for btn_key in menu.layout_keys(screen["menu"]):
            label_raw = (form.get(f"label_{btn_key}") or "").strip()
            default_label = menu.BUTTON_DEFS[btn_key][0]
            label = None if (not label_raw or label_raw == default_label) else label_raw
            is_visible = form.get(f"visible_{btn_key}") is not None
            await repo.upsert_menu_button(pool, btn_key, label, is_visible)

    logger.info("Админка: текст экрана «{}» сохранён", key)
    return RedirectResponse(f"/screens/{key}?ok=1", status_code=303)
