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
    # Как часто опрашивать pending-платежи (минуты).
    payment_poll_interval_min: int = 1
    # Как часто проверять окончания подписок (минуты) — кик из группы + уведомление.
    # Ставь 1 для проверки каждую минуту (тест), 60 — раз в час и т.д.
    expiry_check_interval_min: int = 30
    # Единица длительности подписки: "months" (прод) или "minutes" (ТЕСТ окончаний).
    # В режиме minutes «1/3/6/12» считаются минутами и в end_date, и в подписях кнопок —
    # подписка истекает за минуты, чтобы вживую увидеть авто-кик из группы.
    subscription_unit: str = "months"
    # Чек 54-ФЗ: ВРЕМЕННАЯ заглушка email покупателя.
    # АРХИТЕКТУРА: реальный email берётся из users.email (см. services.receipt),
    # эта заглушка — fallback, пока сбор email не включён. Меняется одной настройкой.
    receipt_email_placeholder: str = "receipt@example.com"

    # ── Прочее ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    @field_validator("db_schema")
    @classmethod
    def _validate_schema(cls, v: str) -> str:
        # Защита от инъекции: имя схемы попадает в DDL/search_path напрямую.
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v):
            raise ValueError(f"Недопустимое имя схемы: {v}")
        return v

    @field_validator("subscription_unit")
    @classmethod
    def _validate_unit(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("months", "minutes"):
            raise ValueError("subscription_unit должен быть 'months' или 'minutes'")
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
