# Бот клуба «11:11»

Telegram-бот онлайн-клуба с ежемесячной подпиской: приём заявок, оплата через ЮKassa,
авто-управление доступом в закрытую группу, напоминания о продлении.

Стек: Python 3.12 · aiogram 3 · Postgres 16 (схема `club_bot`) · Redis · Loguru ·
Alembic · APScheduler · Docker. Режим — polling (без вебхука).

> Прогресс по этапам — в [`docs/STATUS.md`](docs/STATUS.md) и [`docs/07_ROADMAP.md`](docs/07_ROADMAP.md).

## Быстрый старт (локально)

1. Установите **Docker Desktop**.
2. Создайте `.env` из примера и впишите токен бота:
   ```cmd
   copy .env.example .env
   ```
   Откройте `.env`, заполните `BOT_TOKEN` (от @BotFather) и `ADMIN_IDS` (ваш id от @userinfobot).
3. Запустите весь стек одной командой (бот + Postgres + Redis, с авто-перезапуском при изменении кода):
   ```cmd
   docker compose -f docker-compose.dev.yml up --build
   ```
4. Напишите боту `/start` — он ответит приветствием. Логи действий идут прямо в терминал.

Остановить: `Ctrl+C`, затем при необходимости:
```cmd
docker compose -f docker-compose.dev.yml down
```
Полностью снести локальную БД: `docker compose -f docker-compose.dev.yml down -v`.

Можно также запустить через `start.bat` (двойной клик) — он делает то же самое.

### Hot-reload (аналог `npm run dev`)

В dev-режиме исходники смонтированы в контейнер, а `watchfiles` следит за `src/` и
`migrations/`. Любое изменение `.py` автоматически перезапускает бота — пересобирать
образ не нужно.

### Подключиться к уже запущенным на ПК Postgres/Redis (вместо встроенных)

По умолчанию dev-стек поднимает **свои** Postgres и Redis (изолированно, чтобы не
конфликтовать с другими проектами; бот всё равно живёт в отдельной схеме `club_bot`).
Если нужно использовать уже работающие на ПК контейнеры pg/redis:

1. Уберите/закомментируйте сервисы `postgres` и `redis` и блок `environment` бота в
   `docker-compose.dev.yml`.
2. В `.env` пропишите `DATABASE_URL` и `REDIS_URL`, указывающие на ваши инстансы
   (например, через `host.docker.internal:PORT`), и подключите бот к их docker-сети.
3. Схема `club_bot` создаётся автоматически — существующие таблицы других проектов не затрагиваются.

## Прод / сервер

Деплой настраивается на этапе 9 (CI/CD GitHub Actions + `scripts/install.sh`).
Прод-стек — `docker compose up -d --build` (см. `docker-compose.yml`).

## Миграции

Применяются автоматически при старте бота (Alembic `upgrade head`). Новая миграция:
```cmd
docker compose -f docker-compose.dev.yml run --rm bot alembic revision -m "описание"
```
(файлы появляются в `migrations/versions/`).
