"""Админ-команды. Этап 2 — управление тарифами/длительностями + ручное добавление
участника (для подсчёта мест и как задел под этап 8). Полный набор — этап 8.

Доступ — только для id из ADMIN_IDS.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
import asyncpg
from redis.asyncio import Redis

from .. import repo
from ..config import settings
from ..logger import logger
from ..services import tariffs
from ..utils import add_months, fmt_price

router = Router()


def _is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_id_list


ADMIN_HELP = (
    "<b>АДМИН-КОМАНДЫ</b>\n\n"
    "<b>Тарифы</b>\n"
    "/tiers — список ступеней (цена, лимит мест, занято, активность)\n"
    "/settier &lt;id&gt; price=.. limit=.. active=0|1 name=.. order=.. — изменить ступень\n"
    "    (limit=none — безлимит)\n\n"
    "<b>Длительности</b>\n"
    "/durations — список длительностей\n"
    "/setduration &lt;месяцев&gt; &lt;0|1&gt; — включить/выключить (создаёт, если нет)\n\n"
    "<b>Участники</b>\n"
    "/addmember &lt;tg_id&gt; &lt;tier_id&gt; &lt;месяцев&gt; — вручную выдать подписку\n\n"
    "<i>Изменения тарифов применяются сразу, без перезапуска.</i>"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message):
        return
    await message.answer(ADMIN_HELP)
    logger.info(f"🤖 Бот → @{message.from_user.username or '—'}: /admin (справка)")


@router.message(Command("tiers"))
async def cmd_tiers(message: Message, pool: asyncpg.Pool) -> None:
    if not _is_admin(message):
        return
    tiers = await repo.get_all_tiers(pool)
    occ = await repo.tier_occupancy(pool)
    lines = ["<b>СТУПЕНИ ТАРИФОВ</b>", ""]
    for t in tiers:
        limit = "∞" if t["seat_limit"] is None else str(t["seat_limit"])
        occupied = occ.get(t["id"], 0)
        status = "вкл" if t["is_active"] else "ВЫКЛ"
        lines.append(
            f"<b>#{t['id']}</b> {escape(t['name'])} — {fmt_price(t['monthly_price'])} ₽/мес · "
            f"мест {occupied}/{limit} · {status}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("settier"))
async def cmd_settier(
    message: Message, command: CommandObject, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message):
        return
    args = (command.args or "").split()
    if not args or not args[0].isdigit():
        await message.answer("Формат: /settier &lt;id&gt; price=.. limit=.. active=0|1 name=.. order=..")
        return
    tier_id = int(args[0])
    fields: dict = {}
    for token in args[1:]:
        if "=" not in token:
            continue
        key, val = token.split("=", 1)
        key = key.lower()
        try:
            if key == "price":
                fields["monthly_price"] = Decimal(val.replace(",", "."))
            elif key == "limit":
                fields["seat_limit"] = None if val.lower() in {"none", "-", "0_none"} else int(val)
            elif key == "active":
                fields["is_active"] = val in {"1", "true", "on", "да"}
            elif key == "name":
                fields["name"] = val
            elif key == "order":
                fields["sort_order"] = int(val)
        except (ValueError, InvalidOperation):
            await message.answer(f"Не разобрал значение: <code>{escape(token)}</code>")
            return

    if not fields:
        await message.answer("Нечего менять. Укажите хотя бы одно поле (price/limit/active/name/order).")
        return

    ok = await repo.update_tier(pool, tier_id, **fields)
    if not ok:
        await message.answer(f"Ступень #{tier_id} не найдена.")
        return
    await tariffs.invalidate(redis)  # сразу видно на экране тарифов
    await message.answer(f"Ступень #{tier_id} обновлена: {escape(str(fields))}")
    logger.info(f"⚙️ Админ обновил ступень #{tier_id}: {fields}")


@router.message(Command("durations"))
async def cmd_durations(message: Message, pool: asyncpg.Pool) -> None:
    if not _is_admin(message):
        return
    rows = await repo.get_all_durations(pool)
    lines = ["<b>ДЛИТЕЛЬНОСТИ</b>", ""]
    for r in rows:
        status = "вкл" if r["is_active"] else "ВЫКЛ"
        lines.append(f"{r['months']} мес — {status}")
    await message.answer("\n".join(lines))


@router.message(Command("setduration"))
async def cmd_setduration(
    message: Message, command: CommandObject, pool: asyncpg.Pool, redis: Redis
) -> None:
    if not _is_admin(message):
        return
    args = (command.args or "").split()
    if len(args) != 2 or not args[0].isdigit():
        await message.answer("Формат: /setduration &lt;месяцев&gt; &lt;0|1&gt;")
        return
    months = int(args[0])
    is_active = args[1] in {"1", "true", "on", "да"}
    await repo.upsert_duration(pool, months, is_active)
    await tariffs.invalidate(redis)
    await message.answer(f"Длительность {months} мес → {'включена' if is_active else 'выключена'}.")
    logger.info(f"⚙️ Админ: длительность {months} мес active={is_active}")


@router.message(Command("addmember"))
async def cmd_addmember(
    message: Message, command: CommandObject, pool: asyncpg.Pool
) -> None:
    if not _is_admin(message):
        return
    args = (command.args or "").split()
    if len(args) != 3 or not all(a.lstrip("-").isdigit() for a in args):
        await message.answer("Формат: /addmember &lt;tg_id&gt; &lt;tier_id&gt; &lt;месяцев&gt;")
        return
    tg_id, tier_id, months = int(args[0]), int(args[1]), int(args[2])
    tier = await repo.get_tier(pool, tier_id)
    if tier is None:
        await message.answer(f"Ступень #{tier_id} не найдена.")
        return
    # Пользователь мог ещё не нажимать /start — заводим запись, чтобы FK/логика работали.
    await repo.upsert_user(pool, tg_id, None, None)
    end_date = add_months(datetime.now(timezone.utc), months)
    sub_id = await repo.add_subscription(
        pool, tg_id, tier_id, tier["monthly_price"], months, end_date,
        source="manual", status="active",
    )
    await message.answer(
        f"Подписка #{sub_id} создана: tg_id={tg_id}, тариф «{escape(tier['name'])}» "
        f"({fmt_price(tier['monthly_price'])} ₽/мес), {months} мес, до {end_date:%d.%m.%Y}."
    )
    logger.info(f"⚙️ Админ вручную добавил подписку #{sub_id} для tg_id={tg_id}")
