"""Веб-админка: FastAPI-приложение (этап 11 — каркас + авторизация).

Страницы: вход, выход, смена пароля, дашборд-каркас. Все внутренние страницы
доступны только после входа. Сессия — в подписанной cookie (SessionMiddleware).

Запуск: uvicorn src.webadmin.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from ..cache import close_redis, init_redis
from ..config import settings
from ..db import close_pool, get_pool, init_pool
from ..logger import logger, setup_logging
from . import auth, repo
from .broadcasts import router as broadcasts_router
from .deps import NotAuthenticated, current_admin, templates
from .events import router as events_router
from .menu_buttons import router as menu_buttons_router
from .promos import router as promos_router
from .referral import router as referral_router
from .screens import router as screens_router
from .services import router as services_router
from .settings import router as settings_router
from .stats import router as stats_router
from .subscriptions import router as subscriptions_router
from .tariffs import router as tariffs_router
from .tickets import router as tickets_router

_HERE = Path(__file__).resolve().parent

app = FastAPI(title="Админка 11:11 / Фокус.Энергия", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.admin_web_secret,
    same_site="lax",
    max_age=14 * 24 * 3600,  # 2 недели
)
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
app.include_router(stats_router)
app.include_router(events_router)
app.include_router(tickets_router)
app.include_router(services_router)
app.include_router(referral_router)
app.include_router(subscriptions_router)
app.include_router(tariffs_router)
app.include_router(promos_router)
app.include_router(broadcasts_router)
app.include_router(screens_router)
app.include_router(settings_router)
# Старый раздел «Кнопки меню» (этап 19) свёрнут в «Экраны бота» (этап 22): пункт меню
# убран из навигации, но роутер оставлен для прямых ссылок/закладок.
app.include_router(menu_buttons_router)


@app.exception_handler(NotAuthenticated)
async def _redirect_to_login(request: Request, exc: NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


# ── Жизненный цикл ───────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup() -> None:
    setup_logging(settings.log_level)
    pool = await init_pool()
    # Redis нужен для инвалидации кеша тарифов при правке из веба (этап 23).
    await init_redis()

    # Миграции применяет бот (src.migrate). Ждём появления таблицы admin_users,
    # чтобы не гонять Alembic из двух процессов одновременно.
    for _ in range(60):
        if await repo.table_exists(pool, "admin_users"):
            break
        logger.info("Админка: жду применения миграций (таблица admin_users)...")
        await asyncio.sleep(2)
    else:
        logger.error("Админка: таблица admin_users не появилась — проверьте миграции бота")
        return

    await _seed_first_admin(pool)
    logger.info("✅ Веб-админка готова к работе")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await close_pool()
    await close_redis()


async def _seed_first_admin(pool) -> None:
    """Создаёт первого админа, если их ещё нет."""
    if await repo.count_admins(pool) > 0:
        return
    login = settings.admin_web_login.strip() or "admin"
    password = settings.admin_web_password.strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(9)
        generated = True
    await repo.create_admin(pool, login, auth.hash_password(password))
    if generated:
        logger.warning(
            "Админка: создан первый администратор. Логин: '{}', ПАРОЛЬ (сгенерирован): '{}' "
            "— смените после входа.", login, password
        )
    else:
        logger.info("Админка: создан первый администратор (логин '{}')", login)


# ── Маршруты ─────────────────────────────────────────────────────────────────
@app.get("/login")
async def login_form(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
):
    pool = get_pool()
    row = await repo.get_admin_by_login(pool, login.strip())
    if not row or not row["is_active"] or not auth.verify_password(password, row["password_hash"]):
        logger.info("Админка: неудачный вход (логин '{}')", login.strip())
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    request.session["admin"] = {"id": row["id"], "login": row["login"]}
    await repo.mark_login(pool, row["id"])
    logger.info("Админка: вход выполнен (логин '{}')", row["login"])
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.pop("admin", None)
    return RedirectResponse("/login", status_code=303)


@app.get("/password")
async def password_form(request: Request):
    admin = current_admin(request)
    return templates.TemplateResponse(
        request, "password.html",
        {"admin": admin, "active": "password", "error": None, "ok": False},
    )


@app.post("/password")
async def password_submit(
    request: Request,
    current: str = Form(...),
    new1: str = Form(...),
    new2: str = Form(...),
):
    admin = current_admin(request)
    pool = get_pool()
    row = await repo.get_admin_by_id(pool, admin["id"])

    error = None
    if not row or not auth.verify_password(current, row["password_hash"]):
        error = "Текущий пароль введён неверно"
    elif len(new1) < 6:
        error = "Новый пароль слишком короткий (минимум 6 символов)"
    elif new1 != new2:
        error = "Новые пароли не совпадают"

    if error:
        return templates.TemplateResponse(
            request, "password.html",
            {"admin": admin, "active": "password", "error": error, "ok": False},
            status_code=400,
        )

    await repo.update_password(pool, admin["id"], auth.hash_password(new1))
    logger.info("Админка: пароль изменён (логин '{}')", admin["login"])
    return templates.TemplateResponse(
        request, "password.html",
        {"admin": admin, "active": "password", "error": None, "ok": True},
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
