# Sprint 1: Foundation

**Цель:** закрыть критические инфра-блокеры из аудита перед началом разработки модуля. Никакого нового функционала.

**Длительность:** 2-3 дня по 2-3 часа.

**Зависимости:** ничего — это первый спринт.

**ВАЖНО:** этот спринт делается **внимательно, без многоагентности**. Один Claude Code в режиме «один на один с тобой» через VS Code. Multi-agent через tmux будет включён только начиная со Sprint 3.

---

## Задачи

### T-1-001: Backup перед началом всего

**Type:** setup
**Files:** —
**Acceptance:**
- Создана копия всей папки `AI_Delivery_Team/` на диске в `AI_Delivery_Team_backup_2026-05-15/`
- Создана копия `agency.db` отдельно как `agency.db.before_git_init`
- Если есть VPS — сделан snapshot на стороне провайдера (или хотя бы `tar -czf ai_agency_backup_<date>.tar.gz /var/www/ai_agency/`)

**Estimate:** S (15 минут)
**Depends-on:** —

**Заметки:**
- НЕ начинать ни одну другую задачу пока бэкап не сделан и не проверен (попытаться открыть архив, увидеть что файлы внутри).

---

### T-1-002: Создать .gitignore

**Type:** setup
**Files:** `.gitignore` (новый, в корне `AI_Delivery_Team/`)
**Acceptance:**
- Файл `.gitignore` создан в корне `AI_Delivery_Team/`
- Содержит как минимум:

```
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
venv/
.venv/
*.egg-info/

# Node (Playwright tests)
node_modules/

# Environment
.env
.env.local
.env.*.local
# .env.example НЕ игнорируем — должен быть в репо с плейсхолдерами

# Databases
*.db
*.db-journal
*.db-wal
*.db-shm
_test_*.db
backups/

# Knowledge base contents (большие файлы)
ai_agency/data/knowledge/*
!ai_agency/data/knowledge/.gitkeep

# Logs
*.log
/var/log/

# OS
.DS_Store
Thumbs.db

# IDE
.idea/
.vscode/settings.json

# Pipeline workspaces (будут large)
ai_agency/pipeline_workspaces/

# Старая админка (deprecated)
# (НЕ игнорируем пока, удалим в Sprint 5)
```

**Estimate:** S (10 минут)
**Depends-on:** T-1-001
**Owner:** full-stack

---

### T-1-003: git init и первый коммит

**Type:** setup
**Files:** `.git/` (создаётся), весь существующий код входит в первый коммит
**Acceptance:**
- В корне `AI_Delivery_Team/` выполнено `git init`
- `git config user.name`, `user.email` настроены
- Проверено `git status` — нет файлов которые попадают в репо, но не должны (никаких `.env`, `*.db`, `node_modules`, `__pycache__`, `data/knowledge/`)
- Если `git status` показывает что-то подозрительное — STOP, проанализировать, обновить `.gitignore`, повторить
- Только когда status чистый: `git add .` и `git commit -m "chore: initial import of existing AI_Delivery_Team codebase"`
- `git log --oneline` показывает один коммит

**Estimate:** S (20 минут)
**Depends-on:** T-1-002
**Owner:** full-stack

**Заметки:**
- Это критичный момент. Если в первый коммит попадут `.env` или `agency.db`, потом будет мучительно вычищать. Лучше потратить лишних 10 минут на проверку.
- Команды:
  ```bash
  cd /path/to/AI_Delivery_Team
  git init
  git config user.email "ваш-email@example.com"
  git config user.name "Никита Морус"

  # ПРОВЕРКА: что попадёт в репо
  git status

  # Если ок:
  git add .
  git status   # ещё раз
  git commit -m "chore: initial import of existing AI_Delivery_Team codebase"
  ```

---

### T-1-004: Создать GitHub приватный репозиторий и push

**Type:** setup
**Files:** —
**Acceptance:**
- На github.com создан **приватный** репозиторий (например `ai-delivery-team`)
- Локально:
  ```bash
  git remote add origin git@github.com:<username>/ai-delivery-team.git
  # или HTTPS если SSH не настроен
  git branch -M main
  git push -u origin main
  ```
- Проверено что репозиторий **приватный** (через настройки на GitHub)
- В README репозитория добавлена короткая описалка (опционально)

**Estimate:** S (15 минут)
**Depends-on:** T-1-003
**Owner:** full-stack

---

### T-1-005: Аудит секретов в .env и .env.example

**Type:** security
**Files:** `ai_agency/.env`, `ai_agency/.env.example`
**Acceptance:**
- Прочитан текущий `ai_agency/.env`
- Прочитан текущий `ai_agency/.env.example`
- Создан временный документ `docs/secrets-rotation-checklist.md` со списком ключей которые нужно ротировать:
  - `ANTHROPIC_API_KEY` (из `.env.example` — реальный, должен быть отозван)
  - `TELEGRAM_BOT_TOKEN` (из `.env.example` — реальный, отозвать)
  - `ADMIN_PASSWORD` (текущий `Admin2024` — слабый, заменить на длинный random)
  - `SECRET_KEY` (одинаковый в `.env` и `.env.example` — поменять)
  - `YANDEX_METRIKA_OAUTH_TOKEN` — проверить, надо ли ротировать
- Для каждого ключа в чеклисте — URL/инструкция где его ротировать

**Estimate:** S (30 минут)
**Depends-on:** T-1-004
**Owner:** full-stack

---

### T-1-006: Ротация ANTHROPIC_API_KEY

**Type:** security
**Files:** `ai_agency/.env`
**Acceptance:**
- На console.anthropic.com отозван старый ключ (из `.env.example`)
- Сгенерирован новый ключ
- Новый ключ обновлён в `ai_agency/.env`
- НЕ коммитим — `.env` уже в `.gitignore`
- Запущен `python ai_agency/main.py` локально (WEB_ONLY=true) — проверить что приложение стартует с новым ключом
- Если есть прод — обновить `/var/www/ai_agency/ai_agency/.env` на сервере, перезапустить `systemctl restart ai-agency`

**Estimate:** S (20 минут)
**Depends-on:** T-1-005
**Owner:** full-stack

---

### T-1-007: Ротация TELEGRAM_BOT_TOKEN

**Type:** security
**Files:** `ai_agency/.env`
**Acceptance:**
- В Telegram у `@BotFather` для текущего бота: `/revoke` → новый токен
- Новый токен в `ai_agency/.env`
- На сервере тоже обновлён
- Перезапустить, проверить что бот отвечает на `/start`

**Estimate:** S (15 минут)
**Depends-on:** T-1-005
**Owner:** full-stack

---

### T-1-008: Заменить ADMIN_PASSWORD и SECRET_KEY

**Type:** security
**Files:** `ai_agency/.env`
**Acceptance:**
- Сгенерированы новые случайные значения (`openssl rand -hex 32`)
- `ADMIN_PASSWORD` заменён на новый
- `SECRET_KEY` заменён на новый
- Локально и на сервере
- Проверено: можно залогиниться с новым паролем в HQ

**Estimate:** S (20 минут)
**Depends-on:** T-1-005

---

### T-1-009: Очистить .env.example, оставить только плейсхолдеры

**Type:** security
**Files:** `ai_agency/.env.example`
**Acceptance:**
- Файл переписан: значения заменены на плейсхолдеры
- Пример:
  ```
  ANTHROPIC_API_KEY=sk-ant-api03-REPLACE-ME-WITH-YOUR-KEY
  TELEGRAM_BOT_TOKEN=000000000:REPLACE_ME_WITH_YOUR_BOT_TOKEN
  TELEGRAM_OWNER_ID=000000000
  TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx
  SECRET_KEY=generate-with-openssl-rand-hex-32
  ADMIN_PASSWORD=set-a-long-random-password
  YANDEX_METRIKA_OAUTH_TOKEN=optional-yandex-metrika-token
  ```
- Закоммитить с сообщением `security: replace real secrets in .env.example with placeholders`
- Push в GitHub

**Estimate:** S (10 минут)
**Depends-on:** T-1-006, T-1-007, T-1-008

---

### T-1-010: Удалить чеклист секретов из истории

**Type:** security
**Files:** `docs/secrets-rotation-checklist.md`
**Acceptance:**
- Файл `docs/secrets-rotation-checklist.md` удалён
- Закоммитить `security: remove secrets rotation worksheet`

**Estimate:** S (5 минут)
**Depends-on:** T-1-009

---

### T-1-011: Создать миграцию для таблицы hq_sessions

**Type:** feature
**Files:** `ai_agency/database.py`
**Acceptance:**
- В `database.py` в функции `init_db()` добавлена миграция `_add_hq_sessions_table()`:
  ```python
  async def _add_hq_sessions_table(db: aiosqlite.Connection):
      await db.execute('''
          CREATE TABLE IF NOT EXISTS hq_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              token TEXT NOT NULL UNIQUE,
              user_id INTEGER NOT NULL REFERENCES hq_users(id),
              role TEXT NOT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              expires_at TIMESTAMP NOT NULL,
              last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              ip_address TEXT,
              user_agent TEXT
          )
      ''')
      await db.execute('CREATE INDEX IF NOT EXISTS idx_hq_sessions_token ON hq_sessions(token)')
      await db.execute('CREATE INDEX IF NOT EXISTS idx_hq_sessions_expires ON hq_sessions(expires_at)')
  ```
- Вызов добавлен в `init_db()` в правильном месте (после миграций hq_users)
- Запустить `python main.py` локально (WEB_ONLY=true) — миграция применилась без ошибок
- Проверить sqlite: `sqlite3 agency.db ".schema hq_sessions"`

**Estimate:** M (30 минут)
**Depends-on:** T-1-004

---

### T-1-012: Перенести логику сессий с in-memory на hq_sessions

**Type:** refactor
**Files:** `ai_agency/hq_v3_api.py` (где сейчас `_sessions` dict), возможно `api.py`
**Acceptance:**
- Заменён in-memory `_sessions: dict` на функции работы с таблицей `hq_sessions`:
  - `create_session(user_id, role, ip, ua)` → token, expires_at, insert в БД
  - `get_session(token)` → проверка expires_at, обновление last_activity_at
  - `delete_session(token)` → DELETE WHERE token=?
  - `cleanup_expired_sessions()` → DELETE WHERE expires_at < now() (вызывается раз в час)
- Все места где используется `_sessions` обновлены
- При логине — новая сессия пишется в `hq_sessions`
- При логауте — DELETE из БД
- При проверке токена в `require_role` — SELECT из БД
- E2E проверка:
  1. Залогиниться в HQ через `/api/auth/login`
  2. `systemctl restart ai-agency` (или перезапустить локально)
  3. Запрос с тем же токеном к `/api/auth/me` → должен работать (НЕ 401)
- Закоммитить: `refactor(auth): migrate in-memory sessions to hq_sessions table`

**Estimate:** L (90 минут)
**Depends-on:** T-1-011
**Owner:** backend

**Заметки:**
- Это самая «опасная» задача спринта — трогает auth. Делать в feature-branch:
  ```bash
  git checkout -b feature/db-sessions
  # ... работа ...
  git push -u origin feature/db-sessions
  # PR в main через GitHub
  ```
- После мерджа — обязательно ручной smoke-test что логин работает.

---

### T-1-013: Проверить delivery.html и /api/delivery/* эндпоинты

**Type:** bugfix
**Files:** `static/hq/delivery.html`, проверка `api.py` + `hq_v3_api.py`
**Acceptance:**
- Найти где определены `/api/delivery/overview`, `/api/delivery/projects`, `/api/delivery/templates` (grep по всем `.py`)
- Если нет в коде:
  - Создать минимальные stub-эндпоинты которые возвращают данные из существующих `delivery_*` таблиц
  - Реализация: `SELECT * FROM delivery_projects` для `/projects`, агрегаты по статусам для `/overview`, `SELECT * FROM delivery_templates` для `/templates`
- Если есть в коде но не работают — починить
- Проверить `delivery.html` в браузере:
  - Метрики отображаются
  - Список проектов отображается
  - Шаблоны загружаются
- Закоммитить

**Estimate:** M (45-60 минут)
**Depends-on:** T-1-012
**Owner:** backend

---

### T-1-014: Установить tmux на сервере (если ещё нет)

**Type:** setup
**Files:** —
**Acceptance:**
- На сервере выполнено `which tmux`
- Если нет: `sudo apt install -y tmux`
- Проверка: `tmux -V` показывает версию
- Создание тестовой сессии: `tmux new -d -s test`, `tmux ls`, `tmux kill-session -t test`

**Estimate:** S (10 минут)
**Depends-on:** —

---

### T-1-015: Установить ротацию бэкапов

**Type:** ops
**Files:** новый скрипт `ai_agency/scripts/rotate_backups.sh` или python
**Acceptance:**
- Создан скрипт который оставляет последние 30 бэкапов в `backups/`, удаляет остальные
- Добавлен в cron на сервере: `0 4 * * * /var/www/ai_agency/scripts/rotate_backups.sh`
- Или вызов из `database.py` после создания каждого бэкапа

**Estimate:** S (20 минут)
**Depends-on:** —

---

## Definition of done for sprint 1

- [ ] T-1-001..T-1-015 выполнены
- [ ] Все коммиты в `main` (после ревью PR-ов)
- [ ] `git log` показывает чистую историю с осмысленными сообщениями
- [ ] В `.env.example` только плейсхолдеры
- [ ] Старые секреты отозваны на провайдерах
- [ ] Локально: HQ запускается, можно залогиниться, сессия переживает рестарт
- [ ] На сервере: то же
- [ ] `delivery.html` работает в браузере
- [ ] Бэкапы ротируются

## Acceptance demo

После Sprint 1 ты должен мочь:

1. `git log --oneline` показывает 5-10 чистых коммитов
2. На GitHub в репо видна история, проект приватный
3. `cat ai_agency/.env.example` — только плейсхолдеры, никаких реальных ключей
4. `systemctl restart ai-agency` (или локальный рестарт) → залогинен в HQ → сессия не сброшена
5. `sqlite3 agency.db ".tables" | grep hq_sessions` — таблица есть
6. `delivery.html` открывается, метрики/проекты/шаблоны видны
7. Старый ANTHROPIC_API_KEY больше не работает (проверить через curl на api.anthropic.com)

После этого можно переходить к Sprint 2.

## Что НЕ делаем в Sprint 1

- НЕ создаём pipeline/ модуль (это Sprint 2)
- НЕ добавляем новые таблицы кроме `hq_sessions`
- НЕ трогаем `orchestrator.py`, `agents/`, `telegram_bot.py`
- НЕ меняем UI кроме починки `delivery.html`
- НЕ ставим `claude-agent-sdk` (это Sprint 2)
