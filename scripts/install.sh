#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Установщик Telegram-бота клуба «11:11» на чистой Ubuntu.
# Поднимает самодостаточный стек: бот + свой Postgres + Redis в одном docker-compose.
# Данные — в именованных томах, автоперезапуск. Использование:  bash install.sh
# ─────────────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
prompt()  { read -rp "$(echo -e "${YELLOW}>>> $1: ${NC}")" "$2"; }
promptp() { read -rsp "$(echo -e "${YELLOW}>>> $1: ${NC}")" "$2"; echo; }

echo ""
echo "=========================================================="
echo "   Бот клуба «11:11» — установщик для Ubuntu"
echo "=========================================================="
echo ""

# ── Сбор переменных ──────────────────────────────────────────────────────────
prompt  "Git репозиторий (https://github.com/...)" GIT_REPO
GIT_REPO=${GIT_REPO:-https://github.com/dimatolpygin/club_order.git}

prompt  "Ветка для деплоя [master]" BRANCH
BRANCH=${BRANCH:-master}

prompt  "Каталог установки [/opt/club_bot]" INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/opt/club_bot}

echo ""
promptp "BOT_TOKEN (от @BotFather)" BOT_TOKEN
prompt  "ADMIN_IDS (id админов через запятую)" ADMIN_IDS
prompt  "CLUB_CHAT_ID (числовой id супергруппы -100...)" CLUB_CHAT_ID
prompt  "CLUB_CHAT_INVITE_URL (инвайт-ссылка с заявкой на вступление)" CLUB_CHAT_INVITE_URL

echo ""
prompt  "YOOKASSA_SHOP_ID" YOOKASSA_SHOP_ID
promptp "YOOKASSA_SECRET_KEY" YOOKASSA_SECRET_KEY
prompt  "YOOKASSA_RETURN_URL (Enter — соберётся как ссылка на бота)" YOOKASSA_RETURN_URL

echo ""
prompt  "RECEIPT_EMAIL_PLACEHOLDER [receipt@example.com]" RECEIPT_EMAIL_PLACEHOLDER
RECEIPT_EMAIL_PLACEHOLDER=${RECEIPT_EMAIL_PLACEHOLDER:-receipt@example.com}

echo ""
echo "S3-хранилище для фото в рассылке (необязательно; Enter — пропустить)."
prompt  "S3_ENDPOINT" S3_ENDPOINT
prompt  "S3_REGION" S3_REGION
prompt  "S3_BUCKET" S3_BUCKET
prompt  "S3_ACCESS_KEY" S3_ACCESS_KEY
promptp "S3_SECRET_KEY" S3_SECRET_KEY
prompt  "S3_PUBLIC_BASE_URL (обычно = S3_ENDPOINT)" S3_PUBLIC_BASE_URL

# Пароль для встроенного Postgres генерируется автоматически.
POSTGRES_PASSWORD=$(openssl rand -hex 24)

echo ""
info "Начинаю установку..."

# ── Docker ───────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  info "Устанавливаю Docker..."
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version &>/dev/null; then
  error "Не найден плагин 'docker compose'. Установите docker-compose-plugin и повторите."
fi
info "Docker: $(docker --version)"

# ── git ──────────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  info "Устанавливаю git..."
  apt-get update -qq && apt-get install -y -qq git
fi

# ── Клонирование / обновление ────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
  warn "Каталог уже существует — обновляю..."
  cd "$INSTALL_DIR"
  git fetch --all
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
else
  info "Клонирую репозиторий ($BRANCH)..."
  git clone --branch "$BRANCH" "$GIT_REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# ── .env ─────────────────────────────────────────────────────────────────────
# Если .env уже есть — сохраняем прежний пароль БД, чтобы не потерять данные.
if [[ -f .env ]] && grep -q '^POSTGRES_PASSWORD=' .env; then
  POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-)
  warn "Использую существующий POSTGRES_PASSWORD из .env"
fi

info "Создаю .env (боевые интервалы)..."
cat > .env <<ENVEOF
# Telegram
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
CLUB_CHAT_ID=${CLUB_CHAT_ID}
CLUB_CHAT_INVITE_URL=${CLUB_CHAT_INVITE_URL}

# База данных (встроенный Postgres)
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DB_SCHEMA=club_bot

# ЮKassa
YOOKASSA_SHOP_ID=${YOOKASSA_SHOP_ID}
YOOKASSA_SECRET_KEY=${YOOKASSA_SECRET_KEY}
YOOKASSA_RETURN_URL=${YOOKASSA_RETURN_URL}
PAYMENT_POLL_INTERVAL_MIN=1

# Проверка окончаний подписок (минуты)
EXPIRY_CHECK_INTERVAL_MIN=30

# Напоминания о продлении (боевые: проверка раз в час, пороги 3/1/0 дня)
REMINDER_CHECK_INTERVAL_MIN=60
REMINDER_UNIT=day
REMINDER_EARLY_OFFSET=3
REMINDER_SOON_OFFSET=1
REMINDER_LAST_OFFSET=0

# Чек 54-ФЗ: заглушка email
RECEIPT_EMAIL_PLACEHOLDER=${RECEIPT_EMAIL_PLACEHOLDER}

# S3-хранилище (фото в рассылке)
S3_ENDPOINT=${S3_ENDPOINT}
S3_REGION=${S3_REGION}
S3_BUCKET=${S3_BUCKET}
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
S3_PUBLIC_BASE_URL=${S3_PUBLIC_BASE_URL}

# Прочее
LOG_LEVEL=INFO
ENVEOF
chmod 600 .env

# ── Запуск ───────────────────────────────────────────────────────────────────
info "Собираю и запускаю стек (бот + Postgres + Redis)..."
docker compose up -d --build

echo ""
echo "=========================================================="
info "Установка завершена!"
echo ""
echo "  Каталог:   ${INSTALL_DIR}"
echo "  Логи:      docker compose -f ${INSTALL_DIR}/docker-compose.yml logs -f bot"
echo "  Рестарт:   docker compose -f ${INSTALL_DIR}/docker-compose.yml restart"
echo "  Стоп:      docker compose -f ${INSTALL_DIR}/docker-compose.yml down"
echo ""
warn "Не забудьте сделать бота администратором группы ${CLUB_CHAT_ID} (право одобрять заявки и банить)!"
echo "=========================================================="
