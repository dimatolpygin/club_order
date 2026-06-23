"""Точка входа: миграции (Alembic), инициализация БД/Redis, запуск бота (polling)."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import __version__
from .cache import close_redis, init_redis
from .config import settings
from .db import close_pool, init_pool
from .handlers import get_main_router
from .logger import setup_logging
from .middlewares import LoggingMiddleware
from .services import app_settings, payments, referral_jobs, reminders, subscriptions


async def main() -> None:
    log = setup_logging(settings.log_level)
    log.info(f"⏳ Запуск бота клуба «11:11» (v{__version__})...")

    pool = await init_pool()
    redis = await init_redis()

    # Доп-администраторы (добавленные из админки) — в in-memory кеш, чтобы
    # проверка прав оставалась синхронной.
    extra_admins = await app_settings.load_extra_admins(pool)
    if extra_admins:
        log.info(f"Доп-администраторы из БД: {sorted(extra_admins)}")

    # FSM-состояния храним в Redis. parse_mode=HTML включён глобально.
    storage = RedisStorage.from_url(settings.redis_url)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Зависимости, доступные во всех хендлерах как аргументы pool / redis.
    dp["pool"] = pool
    dp["redis"] = redis

    dp.update.middleware(LoggingMiddleware())
    dp.include_router(get_main_router())

    # Фоновый поллер pending-платежей ЮKassa (домена нет → без вебхука).
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        payments.poll_pending,
        "interval",
        minutes=settings.payment_poll_interval_min,
        args=[pool, bot],
        id="poll_pending_payments",
        max_instances=1,
        coalesce=True,
    )
    # Фоновая проверка окончаний подписок: статус expired + кик из группы + уведомление.
    scheduler.add_job(
        subscriptions.run_expiry_check,
        "interval",
        minutes=settings.expiry_check_interval_min,
        args=[pool, bot],
        id="expire_subscriptions",
        max_instances=1,
        coalesce=True,
    )
    # Напоминания о продлении: за несколько дней / за день / в последний день.
    scheduler.add_job(
        reminders.run_reminder_check,
        "interval",
        minutes=settings.reminder_check_interval_min,
        args=[pool, bot],
        id="send_reminders",
        max_instances=1,
        coalesce=True,
    )
    # Реферальные бонусы: после даты бани начисляем пригласившему (этап 17).
    # Частоту берём как у проверки окончаний — отдельный инфра-параметр не вводим.
    scheduler.add_job(
        referral_jobs.run_referral_accrual,
        "interval",
        minutes=settings.expiry_check_interval_min,
        args=[pool, bot],
        id="accrue_referral_bonuses",
        max_instances=1,
        coalesce=True,
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([
            BotCommand(command="start", description="Главный экран"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="sub", description="Статус моей подписки"),
            BotCommand(command="id", description="Показать мой Telegram ID"),
        ])
        me = await bot.get_me()
        scheduler.start()
        # Явно запрашиваем нужные типы апдейтов. Без chat_join_request заявки в группу
        # не доходят до бота (этап 4) — поэтому резолвим по зарегистрированным хендлерам.
        allowed = dp.resolve_used_update_types()
        log.info(
            f"✅ Бот @{me.username} запущен (polling); поллер платежей каждые "
            f"{settings.payment_poll_interval_min} мин; проверка окончаний каждые "
            f"{settings.expiry_check_interval_min} мин; напоминания каждые "
            f"{settings.reminder_check_interval_min} мин "
            f"(пороги {settings.reminder_early_offset}/{settings.reminder_soon_offset}/"
            f"{settings.reminder_last_offset} {settings.reminder_unit}); "
            f"апдейты: {allowed}"
        )
        await dp.start_polling(bot, allowed_updates=allowed)
    finally:
        log.info("Останавливаю бота...")
        scheduler.shutdown(wait=False)
        await close_redis()
        await close_pool()
        await bot.session.close()


def run() -> None:
    # Миграции применяем ДО основного event loop: Alembic (async) сам поднимает
    # временный loop, поэтому вызывать его внутри работающего loop нельзя.
    setup_logging(settings.log_level)
    from .migrate import run_migrations

    run_migrations()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    run()
