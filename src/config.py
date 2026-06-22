"""Конфигурация проекта. Все значения берутся из переменных окружения (.env)."""
from __future__ import annotations

import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Telegram ─────────────────────────────────────────────────────────────
    bot_token: str
    admin_ids: str = ""

    # Закрытая группа клуба (этап 4). На этапе 0 не обязательно.
    club_chat_id: str = ""
    club_chat_invite_url: str = ""

    # Ссылка на аккаунт поддержки (кнопка «Перейти» в разделе «Поддержка»).
    # Обычно задаётся из админки (bot_settings) — это .env-fallback.
    support_url: str = ""

    # ── База данных ──────────────────────────────────────────────────────────
    # DSN для asyncpg (runtime). Пример: postgresql://user:pass@host:5432/db
    database_url: str
    # Отдельная схема под этот бот — чужие таблицы на ПК НЕ трогаем.
    db_schema: str = "club_bot"

    # ── Redis (FSM + кеш) ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── ЮKassa (этап 3) ──────────────────────────────────────────────────────
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    # Куда ЮKassa вернёт пользователя после оплаты. Если пусто — соберётся
    # автоматически как ссылка на бота (https://t.me/<username>).
    yookassa_return_url: str = ""
    # Прокси для запросов к API ЮKassa (нужен, если сервер не в РФ — ЮKassa режет
    # зарубежные IP). Пусто — напрямую. Примеры:
    #   http://user:pass@host:port   ·   socks5://user:pass@host:port
    yookassa_proxy: str = ""
    # Как часто опрашивать pending-платежи (минуты).
    payment_poll_interval_min: int = 1
    # Как часто проверять окончания подписок (минуты) — кик из группы + уведомление.
    # Ставь 1 для проверки каждую минуту (тест), 60 — раз в час и т.д.
    expiry_check_interval_min: int = 30

    # ── Напоминания о продлении (этап 6) ─────────────────────────────────────
    # Как часто прогонять проверку напоминаний (минуты).
    reminder_check_interval_min: int = 60
    # Единица измерения порогов напоминаний: minute/hour/day/month.
    # Для теста ставь minute, чтобы все три напоминания успели прийти за минуты.
    reminder_unit: str = "day"
    # Пороги (в reminder_unit): сколько целых единиц должно остаться до конца,
    # чтобы пришло соответствующее напоминание. early ≥ soon ≥ last.
    #   early — «осталось N дней» (экран 14)
    #   soon  — «завтра заканчивается» (экран 15)
    #   last  — «сегодня последний день» (экран 16)
    reminder_early_offset: int = 3
    reminder_soon_offset: int = 1
    reminder_last_offset: int = 0
    # Чек 54-ФЗ: ВРЕМЕННАЯ заглушка email покупателя.
    # АРХИТЕКТУРА: реальный email берётся из users.email (см. services.receipt),
    # эта заглушка — fallback, пока сбор email не включён. Меняется одной настройкой.
    receipt_email_placeholder: str = "receipt@example.com"

    # ── S3-хранилище (фото в рассылке, этап 8) ───────────────────────────────
    # S3-совместимое хранилище (Beget). Пусто — загрузка фото отключена,
    # рассылка работает только текстом.
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # Базовый публичный URL (обычно совпадает с endpoint). Итоговая ссылка —
    # f"{s3_public_base_url}/{s3_bucket}/{key}".
    s3_public_base_url: str = ""

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key)

    # ── Веб-админка (цикл 2, этап 11) ────────────────────────────────────────
    # Секрет для подписи cookie-сессии админки. В ПРОДЕ обязательно задать свой
    # длинный случайный (ADMIN_WEB_SECRET в .env) — иначе сессии подделываемы.
    admin_web_secret: str = "dev-insecure-change-me"
    # Сид первого администратора веб-панели. Создаётся при первом старте, если
    # таблица админов пуста. Если пароль пуст и админов ещё нет — будет
    # сгенерирован случайный и выведен в лог (для локального старта).
    admin_web_login: str = "admin"
    admin_web_password: str = ""

    # ── Прочее ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    @field_validator("db_schema")
    @classmethod
    def _validate_schema(cls, v: str) -> str:
        # Защита от инъекции: имя схемы попадает в DDL/search_path напрямую.
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v):
            raise ValueError(f"Недопустимое имя схемы: {v}")
        return v

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x]

    @property
    def club_chat_id_int(self) -> int | None:
        """Числовой id группы клуба (для сравнения с chat_join_request). None — не задан."""
        raw = self.club_chat_id.strip()
        if not raw or not raw.lstrip("-").isdigit():
            return None
        return int(raw)

    @property
    def sqlalchemy_url(self) -> str:
        """URL для SQLAlchemy/Alembic — тот же Postgres, но через драйвер asyncpg."""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
