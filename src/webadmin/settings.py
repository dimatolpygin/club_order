"""Раздел админки «Настройки» (этап 27) — перенос из бот-команды /admin.

Объединяет на одной странице оставшиеся разделы старой панели /admin:
  - напоминания о продлении (единица + пороги early/soon/last);
  - ссылка поддержки (кнопка «Перейти» у пользователя);
  - администраторы доступа (доп-админы бота по tg_id);
  - FSM-диагностика «кто на каком экране» (read-only).

Все значения живут в bot_settings (services.app_settings) — тот же источник
истины, что у бота. Напоминания и ссылку бот читает из БД на каждом проходе/рендере
(применяются сразу). Доп-админов бот держит в in-memory кеше и перечитывает из БД
периодическим джобом (main.py) — поэтому правки здесь применяются в боте в течение
минуты, без рестарта. Все POST — через PRG-redirect.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import repo
from ..config import settings
from ..db import get_pool
from ..logger import logger
from ..services import app_settings
from ..texts import UNIT_LABELS
from .deps import current_admin, templates

router = APIRouter()

_REM_KINDS = (
    ("early", "Раннее («осталось N»)"),
    ("soon", "«Завтра заканчивается»"),
    ("last", "Последний день"),
)

# Человеческие подписи экранов (коды state из repo.set_fsm_state). Префиксные
# (с динамическим хвостом) обрабатываются отдельно ниже.
_FSM_LABELS = {
    "screen:start": "Главный экран (/start)",
    "screen:menu": "Главное меню",
    "screen:about": "Что внутри клуба",
    "screen:rules": "Правила участия",
    "screen:support": "Поддержка",
    "screen:tariffs": "Выбор тарифа",
    "screen:renew": "Продление подписки",
    "screen:mysub": "Моя подписка",
    "screen:pay:pending": "Оплата — ожидание оплаты",
    "screen:pay:success": "Оплата — успех",
    "screen:pay:canceled": "Оплата — отменена",
    "screen:promo": "Ввод промокода",
    "screen:promo:applied": "Промокод применён (выбор срока)",
    "screen:events": "Мероприятия — список",
    "screen:mytickets": "Мои билеты",
    "screen:referral": "Реферальная программа",
    "screen:ticket:pay": "Билет — оплата",
    "screen:ticket:paid": "Билет — оплачен",
    "screen:ticket:canceled": "Билет — отменён",
}

_FSM_PREFIXES = (
    ("screen:yoga:summary:", "Йога — оформление"),
    ("screen:yoga:product:", "Йога — выбор количества"),
    ("screen:yoga", "Йога — раздел"),
    ("screen:summary:", "Оформление заказа (сводка)"),
    ("screen:event:", "Мероприятие — карточка"),
    ("screen:ticket:address:", "Билет — адрес"),
    ("screen:ticket:promo:", "Билет — ввод промокода"),
    ("screen:ticket:", "Билет — выбор"),
    ("screen:myticket:refund:sent:", "Мой билет — заявка на возврат отправлена"),
    ("screen:myticket:refund:", "Мой билет — запрос возврата"),
    ("screen:myticket:", "Мой билет — карточка"),
)


def _fsm_label(state: str | None) -> str:
    if not state:
        return "—"
    if state in _FSM_LABELS:
        return _FSM_LABELS[state]
    for prefix, label in _FSM_PREFIXES:
        if state.startswith(prefix):
            return label
    return state


def _ago(dt: datetime, now: datetime) -> str:
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 3600:
        return f"{secs // 60} мин назад"
    if secs < 86400:
        return f"{secs // 3600} ч назад"
    return f"{secs // 86400} дн назад"


def _normalize_support_url(raw: str) -> str | None:
    """Ввод админа → валидный URL для кнопки. None — не распознано.

    @username / голый username → https://t.me/username; t.me/... → https://...;
    http(s)://… и tg://… — как есть. (Та же логика, что в боте /admin.)
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith(("https://", "http://", "tg://")):
        return raw
    if raw.startswith("t.me/"):
        return "https://" + raw
    if raw.startswith("@"):
        raw = raw[1:]
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw):
        return "https://t.me/" + raw
    return None


async def _overview(request: Request, *, ok: str | None = None, error: str | None = None,
                    status: int = 200):
    pool = get_pool()
    cfg = await app_settings.reminder_config(pool)
    support = await app_settings.support_url(pool)
    manager = await app_settings.manager_url(pool)
    extra = await app_settings.get_extra_admins(pool)
    rows = await repo.get_fsm_stuck(pool)
    now = datetime.now(timezone.utc)
    fsm = [
        {
            "screen": _fsm_label(r["state"]),
            "username": f"@{r['username']}" if r["username"] else "—",
            "name": r["first_name"] or "",
            "tg_id": r["tg_id"],
            "ago": _ago(r["updated_at"], now),
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request, "settings.html",
        {
            "active": "settings", "admin": request.session.get("admin"),
            "unit": cfg["unit"], "unit_label": UNIT_LABELS.get(cfg["unit"], cfg["unit"]),
            "unit_labels": UNIT_LABELS, "offsets": cfg["offsets"],
            "rem_kinds": _REM_KINDS,
            "check_interval": settings.reminder_check_interval_min,
            "support_url": support,
            "manager_url": manager,
            "env_admins": sorted(settings.admin_id_list),
            "extra_admins": extra,
            "fsm": fsm,
            "ok": ok, "error": error,
        },
        status_code=status,
    )


@router.get("/settings")
async def settings_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


@router.post("/settings/reminders")
async def settings_reminders(
    request: Request,
    unit: str = Form(...),
    early: str = Form(...),
    soon: str = Form(...),
    last: str = Form(...),
):
    current_admin(request)
    pool = get_pool()
    if unit not in app_settings.VALID_UNITS:
        return await _overview(request, error="Неизвестная единица напоминаний.", status=400)
    values: dict[str, int] = {}
    for kind, raw in (("early", early), ("soon", soon), ("last", last)):
        raw = (raw or "").strip()
        if not raw.isdigit():
            return await _overview(
                request, error="Пороги напоминаний — целые числа (0 или больше).", status=400
            )
        values[kind] = int(raw)
    await app_settings.set_reminder_unit(pool, unit)
    for kind, value in values.items():
        await app_settings.set_reminder_offset(pool, kind, value)
    logger.info(
        "Админка: напоминания unit={} early={} soon={} last={}",
        unit, values["early"], values["soon"], values["last"],
    )
    return RedirectResponse("/settings?ok=Напоминания сохранены.", status_code=303)


@router.post("/settings/support")
async def settings_support(request: Request, url: str = Form("")):
    current_admin(request)
    pool = get_pool()
    raw = (url or "").strip()
    if not raw:
        await app_settings.set_support_url(pool, "")
        logger.info("Админка: ссылка поддержки очищена")
        return RedirectResponse(
            "/settings?ok=Ссылка поддержки очищена — кнопка «Перейти» скрыта.",
            status_code=303,
        )
    normalized = _normalize_support_url(raw)
    if not normalized:
        return await _overview(
            request,
            error="Не похоже на ссылку. Укажите @username или ссылку вида https://t.me/…",
            status=400,
        )
    await app_settings.set_support_url(pool, normalized)
    logger.info("Админка: ссылка поддержки = {}", normalized)
    return RedirectResponse("/settings?ok=Ссылка поддержки сохранена.", status_code=303)


@router.post("/settings/manager")
async def settings_manager(request: Request, url: str = Form("")):
    """Контакт менеджера услуг (йога/консультации) — кнопка после оплаты услуги."""
    current_admin(request)
    pool = get_pool()
    raw = (url or "").strip()
    if not raw:
        # Пусто → возвращаем дефолт (@zhannazlotnikova), контакт не должен исчезать.
        await app_settings.set_manager_url(pool, "")
        logger.info("Админка: контакт менеджера сброшен на дефолт")
        return RedirectResponse(
            "/settings?ok=Контакт менеджера сброшен на дефолт (@zhannazlotnikova).",
            status_code=303,
        )
    normalized = _normalize_support_url(raw)
    if not normalized:
        return await _overview(
            request,
            error="Не похоже на ссылку. Укажите @username или ссылку вида https://t.me/…",
            status=400,
        )
    await app_settings.set_manager_url(pool, normalized)
    logger.info("Админка: контакт менеджера = {}", normalized)
    return RedirectResponse("/settings?ok=Контакт менеджера сохранён.", status_code=303)


@router.post("/settings/admins/add")
async def settings_admin_add(request: Request, tg_id: str = Form(...)):
    current_admin(request)
    pool = get_pool()
    raw = (tg_id or "").strip()
    if not raw.lstrip("-").isdigit():
        return await _overview(request, error="Telegram ID — это целое число.", status=400)
    new_id = int(raw)
    if new_id in settings.admin_id_list:
        return await _overview(
            request, error=f"{new_id} уже основной администратор (из настроек сервера).",
            status=400,
        )
    if new_id in await app_settings.get_extra_admins(pool):
        return await _overview(
            request, error=f"{new_id} уже в списке администраторов.", status=400
        )
    await app_settings.add_extra_admin(pool, new_id)
    logger.info("Админка: добавлен доп-админ {}", new_id)
    return RedirectResponse(
        f"/settings?ok=Администратор {new_id} добавлен.", status_code=303
    )


@router.post("/settings/admins/{tg_id}/remove")
async def settings_admin_remove(request: Request, tg_id: int):
    current_admin(request)
    pool = get_pool()
    await app_settings.remove_extra_admin(pool, tg_id)
    logger.info("Админка: удалён доп-админ {}", tg_id)
    return RedirectResponse(
        f"/settings?ok=Администратор {tg_id} удалён.", status_code=303
    )
