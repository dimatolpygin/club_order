"""Раздел админки «Рассылка» (этап 26) — перенос из бот-команды /admin.

Форма рассылки (аудитория + текст + до 10 фото/альбом). Веб заливает фото в S3
(services.storage, как этап 8) и кладёт задачу в очередь broadcasts (status='pending');
саму отправку делает бот-джоб services.broadcasts (веб-процесс не держит бота). Ниже —
список последних рассылок со статусом и счётчиками (отправлено/заблокировали/ошибки).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import repo
from ..config import settings
from ..db import get_pool
from ..logger import logger
from ..services import storage
from . import events_repo
from .deps import current_admin, templates

router = APIRouter()

MAX_PHOTOS = 10  # лимит Telegram на media_group

# Значение audience для формы «участники события» (в БД хранится как "event:<id>").
AUDIENCE_EVENT = "event"

# Сегменты аудитории: значение repo.AUDIENCE_* → подпись.
AUDIENCES: list[tuple[str, str]] = [
    (repo.AUDIENCE_ALL, "Всем"),
    (repo.AUDIENCE_ACTIVE, "Активным подписчикам"),
    (repo.AUDIENCE_FORMER, "Бывшим подписчикам"),
    (repo.AUDIENCE_NEVER, "Запускавшим без подписки"),
    (AUDIENCE_EVENT, "Участникам события"),
]
_AUD_KEYS = {a for a, _ in AUDIENCES}
_AUD_LABELS = dict(AUDIENCES)

_EVENT_KINDS = {"banya": "Энерго Баня", "retreat": "Ретрит"}

_STATUS_LABELS = {"pending": "в очереди", "sending": "отправляется", "done": "завершена"}


def _audience_label(audience: str, titles: dict[int, str]) -> str:
    """Подпись сегмента для списка рассылок; 'event:<id>' → «Событие: <title>»."""
    if audience.startswith(repo.AUDIENCE_EVENT_PREFIX):
        raw = audience[len(repo.AUDIENCE_EVENT_PREFIX):]
        title = titles.get(int(raw)) if raw.isdigit() else None
        return f"Событие: {title}" if title else "Событие (удалено)"
    return _AUD_LABELS.get(audience, audience)


def _row_view(b, titles: dict[int, str]) -> dict:
    photos = json.loads(b["photos"] or "[]")
    return {
        "id": b["id"],
        "audience": _audience_label(b["audience"], titles),
        "preview": (b["body"][:80] + "…") if b["body"] and len(b["body"]) > 80 else (b["body"] or "—"),
        "photos": len(photos),
        "status": _STATUS_LABELS.get(b["status"], b["status"]),
        "is_done": b["status"] == "done",
        "total": b["total"],
        "sent": b["sent"],
        "blocked": b["blocked"],
        "failed": b["failed"],
        "created_at": b["created_at"].strftime("%d.%m.%Y · %H:%M"),
    }


def _event_option(e) -> dict:
    """Пункт выпадашки события: заголовок + дата + счётчик получателей."""
    return {
        "id": e["id"],
        "label": "{} · {} · {} ({} чел.)".format(
            _EVENT_KINDS.get(e["kind"], e["kind"]),
            e["title"],
            e["starts_at"].strftime("%d.%m.%Y"),
            e["paid_count"],
        ),
    }


async def _overview(request: Request, *, ok: str | None = None, error: str | None = None,
                    status: int = 200):
    pool = get_pool()
    rows = await repo.list_broadcasts(pool, limit=50)
    events = await events_repo.list_events_for_broadcast(pool)
    titles = await events_repo.events_title_map(pool)
    return templates.TemplateResponse(
        request, "broadcasts.html",
        {
            "active": "broadcasts", "admin": request.session.get("admin"),
            "audiences": AUDIENCES, "s3_enabled": settings.s3_enabled,
            "max_photos": MAX_PHOTOS,
            "audience_event": AUDIENCE_EVENT,
            "events": [_event_option(e) for e in events],
            "rows": [_row_view(b, titles) for b in rows],
            "ok": ok, "error": error,
        },
        status_code=status,
    )


@router.get("/broadcasts")
async def broadcasts_page(request: Request, ok: str | None = None, error: str | None = None):
    current_admin(request)
    return await _overview(request, ok=ok, error=error)


@router.post("/broadcasts/create")
async def broadcast_create(
    request: Request,
    audience: str = Form(...),
    event_id: str = Form(""),
    body: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
):
    admin = current_admin(request)
    pool = get_pool()

    if audience not in _AUD_KEYS:
        return await _overview(request, error="Выберите аудиторию.", status=400)

    # «Участники события» → аудитория кодируется как "event:<id>" (этап 48).
    if audience == AUDIENCE_EVENT:
        raw = (event_id or "").strip()
        if not raw.isdigit():
            return await _overview(request, error="Выберите событие.", status=400)
        if not await events_repo.get_event(pool, int(raw)):
            return await _overview(request, error="Событие не найдено.", status=400)
        audience = f"{repo.AUDIENCE_EVENT_PREFIX}{raw}"

    text = (body or "").strip() or None
    # Реальные файлы (пустой input может прислать одну пустую запись без имени).
    files = [f for f in photos if f is not None and f.filename]
    if not text and not files:
        return await _overview(request, error="Добавьте текст или хотя бы одно фото.", status=400)
    if files and not settings.s3_enabled:
        return await _overview(
            request, error="Фото недоступны: хранилище S3 не настроено. Отправьте только текст.",
            status=400,
        )
    if len(files) > MAX_PHOTOS:
        return await _overview(
            request, error=f"Слишком много фото: максимум {MAX_PHOTOS}.", status=400
        )

    uploaded: list[dict] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        ext = "png" if (f.content_type or "").endswith("png") else "jpg"
        try:
            url = await storage.upload_photo(data, ext)
        except Exception as e:  # noqa: BLE001 — не валим всю рассылку из-за одного фото
            logger.error("Рассылка (веб): не удалось загрузить фото в S3: {}", e)
            return await _overview(
                request, error="Не удалось загрузить фото в хранилище. Попробуйте ещё раз.",
                status=400,
            )
        uploaded.append({"url": url})

    if not text and not uploaded:
        return await _overview(request, error="Добавьте текст или хотя бы одно фото.", status=400)

    bid = await repo.create_broadcast(
        pool, audience=audience, body=text, photos=uploaded,
        created_by=admin.get("login"),
    )
    logger.info(
        "Админка: создана рассылка #{} [{}] (фото {}) пользователем {}",
        bid, audience, len(uploaded), admin.get("login"),
    )
    return RedirectResponse(
        f"/broadcasts?ok=Рассылка #{bid} поставлена в очередь — бот отправит её в ближайшую минуту.",
        status_code=303,
    )
