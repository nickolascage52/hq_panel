#!/bin/bash
set -e

echo ""
echo "════════════════════════════════════════════"
echo "  AI Agency Management System — Установка"
echo "════════════════════════════════════════════"
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установи: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "✅ $PYTHON_VERSION"

# Определяем директорию установки
INSTALL_DIR="/var/www/ai_agency"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "📁 Директория установки: $INSTALL_DIR"
echo "📁 Исходные файлы: $SCRIPT_DIR"

# Создание директории
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER:$USER" "$INSTALL_DIR"

# Копирование файлов если запускаем не из целевой папки
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo "📋 Копирование файлов..."
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.env.example "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.env "$INSTALL_DIR/" 2>/dev/null || true
fi

cd "$INSTALL_DIR"

# Виртуальное окружение
if [ ! -d "venv" ]; then
    echo "🔧 Создание виртуального окружения..."
    python3 -m venv venv
else
    echo "✅ Виртуальное окружение уже существует"
fi

source venv/bin/activate
echo "✅ Виртуальное окружение активировано"

# Зависимости
echo "📦 Установка зависимостей..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
echo "✅ Зависимости установлены"

# Создание .env из примера если не существует
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "══════════════════════════════════════════════════"
    echo "  ⚠️  ВАЖНО: Заполни $INSTALL_DIR/.env"
    echo "  Команда: nano $INSTALL_DIR/.env"
    echo ""
    echo "  Обязательно укажи:"
    echo "  - ANTHROPIC_API_KEY (ключ Claude API)"
    echo "  - TELEGRAM_BOT_TOKEN (токен от @BotFather)"
    echo "  - TELEGRAM_OWNER_ID (твой ID в Telegram)"
    echo "  - ADMIN_PASSWORD (пароль для API панели)"
    echo "══════════════════════════════════════════════════"
    echo ""
else
    echo "✅ Файл .env уже существует"
fi

# Создание директории для логов
sudo mkdir -p /var/log
sudo touch /var/log/ai-agency.log /var/log/ai-agency-error.log
sudo chown "$USER:$USER" /var/log/ai-agency.log /var/log/ai-agency-error.log

# Инициализация БД
echo "🗄️  Инициализация базы данных..."
cd "$INSTALL_DIR"
python3 -c "import asyncio; from database import init_db; asyncio.run(init_db())"
echo "✅ База данных готова"

# Systemd сервис для автозапуска
echo "⚙️  Настройка systemd сервиса..."
sudo bash -c "cat > /etc/systemd/system/ai-agency.service << 'SERVICE'
[Unit]
Description=AI Agency Management System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/ai-agency.log
StandardError=append:/var/log/ai-agency-error.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE"

sudo systemctl daemon-reload
sudo systemctl enable ai-agency

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Установка завершена!"
echo "════════════════════════════════════════════"
echo ""
echo "  Следующие шаги:"
echo ""
echo "  1. Заполни .env файл:"
echo "     nano $INSTALL_DIR/.env"
echo ""
echo "  2. Запусти систему:"
echo "     sudo systemctl start ai-agency"
echo ""
echo "  3. Проверь статус:"
echo "     sudo systemctl status ai-agency"
echo ""
echo "  4. Смотри логи:"
echo "     tail -f /var/log/ai-agency.log"
echo ""
echo "  5. API работает на порту 8000:"
echo "     curl http://localhost:8000/api/status"
echo ""
echo "  Полезные команды:"
echo "  - Перезапуск: sudo systemctl restart ai-agency"
echo "  - Остановка:  sudo systemctl stop ai-agency"
echo "  - Логи ошибок: tail -f /var/log/ai-agency-error.log"
echo ""
