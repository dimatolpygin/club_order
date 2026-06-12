@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==========================================================
echo   Бот клуба 11:11 — локальный запуск (dev)
echo ==========================================================
if not exist ".env" (
  echo [ВНИМАНИЕ] Файл .env не найден. Создаю из .env.example...
  copy ".env.example" ".env" > nul
  echo Откройте .env и впишите BOT_TOKEN и ADMIN_IDS, затем запустите снова.
  pause
  exit /b 1
)
docker compose -f docker-compose.dev.yml up --build
pause
