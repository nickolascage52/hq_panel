# Развёртывание AI Agency Management System на VPS

Полная инструкция для установки на VPS-сервер с Ubuntu и ISPmanager.

---

## Что будет после установки

| Адрес | Что работает |
|-------|-------------|
| `yourdomain.ru` | Ваш существующий сайт (без изменений) |
| `yourdomain.ru/hq/` | HQ: дашборд, CRM, AI Команда, аналитика |
| `yourdomain.ru/admin` | Редирект на `/hq/team.html` (старый URL) |
| `yourdomain.ru/api/` | REST API системы |
| Telegram-бот | Управление через личные сообщения |

---

## Шаг 1. Подключение к серверу

### Вариант A: Terminal в ISPmanager

1. Войти в ISPmanager: `https://your-ip:1500` или `https://yourdomain.ru:1500`
2. Левое меню → **Инструменты** → **Shell-клиент** (или Terminal)
3. Откроется терминал в браузере

### Вариант B: SSH с локального компьютера

```bash
ssh root@your-server-ip
```

### Проверка окружения

```bash
python3 --version    # Нужен Python 3.10+
nginx -v             # Нужен Nginx
```

Если Python не установлен:

```bash
apt update && apt install -y python3 python3-pip python3-venv
```

---

## Шаг 2. Загрузка файлов на сервер

### Вариант A: Через файловый менеджер ISPmanager

1. ISPmanager → **Менеджер файлов**
2. Перейти в `/var/www/`
3. Загрузить папку `ai_agency` целиком (или создать и загрузить файлы по одному)
4. Убедиться что все файлы на месте:
   - `requirements.txt`
   - `.env.example`
   - `database.py`
   - `agents/context.py`, `agents/base.py`, `agents/team.py`, `agents/__init__.py`
   - `orchestrator.py`
   - `api.py`
   - `telegram_bot.py`
   - `scheduler.py`
   - `main.py`
   - `install.sh`
   - `setup_nginx.sh`
   - `nginx_addition.conf`
   - `static/admin/index.html`

### Вариант B: Через SCP (с локальной машины)

```bash
scp -r ./ai_agency root@your-server-ip:/var/www/
```

### Вариант C: Через Git (если проект в репозитории)

```bash
cd /var/www
git clone https://github.com/your-user/your-repo.git ai_agency
```

---

## Шаг 3. Установка системы

```bash
cd /var/www/ai_agency
chmod +x install.sh setup_nginx.sh
bash install.sh
```

Скрипт автоматически:
- Создаёт виртуальное окружение Python
- Устанавливает все зависимости
- Инициализирует базу данных SQLite
- Создаёт systemd-сервис для автозапуска
- Копирует `.env.example` в `.env` (если `.env` нет)

---

## Шаг 4. Заполнение .env

Открой файл конфигурации:

```bash
nano /var/www/ai_agency/.env
```

Заполни каждую переменную:

### Claude API (обязательно)

```
ANTHROPIC_API_KEY=sk-ant-api03-ТВОЙ_НАСТОЯЩИЙ_КЛЮЧ
CLAUDE_MODEL=claude-sonnet-4-6
```

Где получить:
1. Зайти на [console.anthropic.com](https://console.anthropic.com)
2. Settings → API Keys → Create Key
3. Скопировать ключ (начинается с `sk-ant-`)
4. Пополнить баланс (минимум $5)

### Telegram бот (обязательно)

```
TELEGRAM_BOT_TOKEN=7123456789:AAH...полный_токен
TELEGRAM_OWNER_ID=123456789
TELEGRAM_CHANNEL_ID=@your_channel
```

**Получить токен бота:**
1. Открыть [@BotFather](https://t.me/BotFather) в Telegram
2. Отправить `/newbot`
3. Придумать имя и username
4. Скопировать токен

**Узнать свой TELEGRAM_OWNER_ID:**
1. Открыть [@userinfobot](https://t.me/userinfobot) в Telegram
2. Отправить `/start`
3. Бот покажет ваш числовой ID

**TELEGRAM_CHANNEL_ID** — username канала для автопубликации (`@mychannel`).
Если канала нет — оставь пустым, публикация будет только через панель.

### Сервер

```
HOST=0.0.0.0
PORT=8000
SECRET_KEY=придумай_длинный_случайный_ключ_минимум_32_символа
ADMIN_PASSWORD=твой_пароль_для_панели
```

**SECRET_KEY** — любая длинная случайная строка. Можно сгенерировать:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**ADMIN_PASSWORD** — этот пароль запрашивается при входе в HQ (`/hq/…`) и для API.

### Публикация

```
AUTO_PUBLISH=false
DAILY_POST_TIME=09:00
TIMEZONE=Europe/Moscow
```

- `AUTO_PUBLISH=false` — автопосты отключены (включи `true` когда убедишься что всё работает)
- `DAILY_POST_TIME` — время ежедневного поста (по московскому времени)

**Сохранить:** `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Шаг 5. Настройка Nginx

Запусти скрипт:

```bash
cd /var/www/ai_agency
bash setup_nginx.sh
```

Скрипт автоматически:
1. Найдёт конфиг nginx для вашего сайта
2. Сделает резервную копию
3. Добавит location блоки для `/hq/`, редиректов `/admin` и `/panel`, `/api/`, `/ws/`
4. Проверит конфигурацию (`nginx -t`)
5. Перезагрузит nginx

### Если скрипт не нашёл конфиг

Найди его вручную:

```bash
# Показать все конфиги nginx
nginx -T 2>/dev/null | grep "server_name"

# Типичные места:
ls /etc/nginx/sites-enabled/
ls /etc/nginx/conf.d/
ls /etc/nginx/vhosts/          # ISPmanager
```

Нашёл? Введи полный путь когда скрипт спросит.

### Если нужно добавить вручную

1. Открой конфиг:

```bash
nano /etc/nginx/sites-enabled/yourdomain.conf
```

2. Найди блок `server { ... }` с вашим доменом

3. Перед закрывающей `}` добавь содержимое файла `nginx_addition.conf`

4. Проверь и примени:

```bash
nginx -t && systemctl reload nginx
```

---

## Шаг 6. Запуск и проверка

### Запуск системы

```bash
sudo systemctl start ai-agency
```

### Проверка статуса

```bash
sudo systemctl status ai-agency
```

Должно показать: `Active: active (running)`

### Проверка API

```bash
curl http://localhost:8000/api/status
```

Должен вернуть JSON со статусом системы.

### Проверка HQ

1. Открыть в браузере: `https://yourdomain.ru/hq/`
2. Ввести пароль из `ADMIN_PASSWORD` в `.env`
3. Должен открыться дашборд HQ

### Тестовая задача через HQ

1. Перейти в **AI Команда** (`/hq/team.html`)
2. Нажать **«Задача всей команде»**, ввести бриф, например: `Напиши пост в Telegram про автоматизацию`
3. Дождаться ответа пайплайна (в чате / уведомлении в интерфейсе)

---

## Шаг 7. Telegram бот

1. Открыть вашего бота в Telegram
2. Отправить `/start`
3. Бот должен ответить приветствием
4. Отправить текст задачи, например: `Напиши пост про чат-ботов для бизнеса`
5. Бот ответит: "Принято. Задача запущена."
6. Через 1-3 минуты придёт результат

### Проверить что бот работает именно с вашим ID

Если бот не отвечает:
- Проверь `TELEGRAM_OWNER_ID` — это должен быть **числовой** ID (не username)
- Перезапусти: `sudo systemctl restart ai-agency`

---

## Полезные команды

```bash
# Статус системы
sudo systemctl status ai-agency

# Перезапуск
sudo systemctl restart ai-agency

# Остановка
sudo systemctl stop ai-agency

# Логи (в реальном времени)
tail -f /var/log/ai-agency.log

# Логи ошибок
tail -f /var/log/ai-agency-error.log

# Последние 50 строк лога
tail -50 /var/log/ai-agency.log

# Проверка что порт слушает
ss -tlnp | grep 8000
```

---

## Решение проблем

### Порт 8000 занят

```bash
# Проверить что занимает порт
ss -tlnp | grep 8000

# Изменить порт в .env
nano /var/www/ai_agency/.env
# Поменять PORT=8000 на PORT=8001

# Обновить nginx конфиг — заменить 8000 на 8001
nano /etc/nginx/sites-enabled/yourdomain.conf
# Найти proxy_pass http://127.0.0.1:8000 → заменить на 8001

# Применить
nginx -t && systemctl reload nginx
sudo systemctl restart ai-agency
```

### Nginx не перезапускается

```bash
# Проверить конфиг
nginx -t

# Показать ошибку
nginx -t 2>&1

# Откатить конфиг если сломали
# (setup_nginx.sh создаёт backup — путь указан в выводе скрипта)
cp /etc/nginx/sites-enabled/yourdomain.conf.backup.ДАТА /etc/nginx/sites-enabled/yourdomain.conf
nginx -t && systemctl reload nginx
```

### Бот не отвечает

```bash
# Проверить токен
grep TELEGRAM_BOT_TOKEN /var/www/ai_agency/.env

# Проверить OWNER_ID
grep TELEGRAM_OWNER_ID /var/www/ai_agency/.env

# Проверить логи на ошибки Telegram
grep -i telegram /var/log/ai-agency.log | tail -20

# Перезапустить
sudo systemctl restart ai-agency
```

### Claude API ошибка

```bash
# Проверить ключ
grep ANTHROPIC_API_KEY /var/www/ai_agency/.env

# Тестовый запрос к API (подставь свой ключ)
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: sk-ant-ТВОЙ_КЛЮЧ" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
```

Если ответ содержит ошибку:
- `authentication_error` → неверный ключ
- `insufficient_funds` → пополни баланс на console.anthropic.com
- `rate_limit_error` → слишком много запросов, подожди минуту

### Панель показывает "Сервер недоступен"

```bash
# Проверить что ai-agency запущен
sudo systemctl status ai-agency

# Проверить что порт слушается
curl http://localhost:8000/api/status

# Проверить nginx
curl -I https://yourdomain.ru/api/status
```

### База данных: сброс (если нужно начать с чистого листа)

```bash
# Остановить систему
sudo systemctl stop ai-agency

# Удалить БД
rm /var/www/ai_agency/agency.db

# Заново инициализировать
cd /var/www/ai_agency
source venv/bin/activate
python3 -c "import asyncio; from database import init_db; asyncio.run(init_db())"

# Запустить
sudo systemctl start ai-agency
```

---

## Обновление системы

При обновлении файлов:

```bash
# Остановить
sudo systemctl stop ai-agency

# Обновить файлы (через SCP, git pull или файловый менеджер)

# Обновить зависимости если изменился requirements.txt
cd /var/www/ai_agency
source venv/bin/activate
pip install -r requirements.txt

# Запустить
sudo systemctl start ai-agency
```

---

## Структура файлов на сервере

```
/var/www/ai_agency/
├── .env                    ← Конфигурация (НЕ коммитить в git!)
├── .env.example            ← Шаблон конфигурации
├── requirements.txt        ← Python-зависимости
├── main.py                 ← Точка входа
├── api.py                  ← FastAPI REST API
├── database.py             ← SQLite модуль
├── orchestrator.py         ← Оркестратор задач
├── telegram_bot.py         ← Telegram бот
├── scheduler.py            ← Планировщик
├── install.sh              ← Скрипт установки
├── setup_nginx.sh          ← Скрипт настройки nginx
├── nginx_addition.conf     ← Location блоки для nginx
├── agency.db               ← База данных (создаётся автоматически)
├── venv/                   ← Виртуальное окружение (создаётся автоматически)
├── agents/
│   ├── __init__.py
│   ├── context.py          ← Профиль агентства
│   ├── base.py             ← Базовый класс агента
│   └── team.py             ← Все 16 агентов с system prompts
└── static/
    └── admin/
        └── index.html      ← Панель управления
```
