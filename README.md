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

Прод-стек самодостаточный (бот + свои Postgres и Redis): `docker-compose.yml`,
данные в именованных томах, миграции применяются при старте.

### Первичная установка на чистой Ubuntu

Одной командой через интерактивный установщик (ставит Docker, клонирует репозиторий,
спрашивает токены/ключи, генерирует пароль БД, поднимает стек):

```bash
curl -fsSL https://raw.githubusercontent.com/dimatolpygin/club_order/master/scripts/install.sh -o install.sh
bash install.sh
```

После установки сделайте бота **администратором** закрытой группы (права одобрять
заявки на вступление и банить — нужно для авто-доступа).

### Автодеплой (CI/CD)

Push в ветку `master` → GitHub Actions заходит на сервер по SSH, делает
`git reset --hard origin/master` и пересобирает стек (`.github/workflows/deploy.yml`).
Разработка ведётся в `dev`; в `master` мержим только когда готовы выкатывать.

Секреты репозитория (Settings → Secrets and variables → Actions):

| Secret | Значение |
|---|---|
| `SERVER_HOST` | IP сервера |
| `SERVER_USER` | пользователь SSH (`root`) |
| `SSH_PRIVATE_KEY` | приватный deploy-ключ целиком (с BEGIN/END) |
| `SERVER_PORT` | порт SSH (необяз., дефолт 22) |
| `INSTALL_DIR` | каталог на сервере (необяз., дефолт `/opt/club_bot`) |

Полезные команды на сервере (из каталога установки):
```bash
docker compose logs -f bot      # логи
docker compose restart          # рестарт
docker compose up -d --build    # пересборка после изменений
```

## Миграции

Применяются автоматически при старте бота (Alembic `upgrade head`). Новая миграция:
```cmd
docker compose -f docker-compose.dev.yml run --rm bot alembic revision -m "описание"
```
(файлы появляются в `migrations/versions/`).
