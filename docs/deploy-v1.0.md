# Deploy v1.0 → Production (89.22.235.144)

**Дата:** 2026-05-15
**Версия:** v1.0.0
**Цель:** перенести все локальные изменения Sprint 1-5 на прод за один заход.

---

## TL;DR (если вы уже всё помните)

```bash
ssh root@89.22.235.144

# 1. Backup
tar -czf /tmp/ai_agency_pre_v1.0_$(date +%Y%m%d_%H%M%S).tar.gz -C /var/www ai_agency
cp /var/www/ai_agency/ai_agency/agency.db /tmp/agency_pre_v1.0.db

# 2. Pull новый код (если git настроен на сервере) или WinSCP файлы
cd /var/www/ai_agency  # или где живёт репо
git pull origin main

# 3. Обновить .env с новыми секретами (см. секцию ниже)
nano /var/www/ai_agency/ai_agency/.env

# 4. Установить новые зависимости
cd /var/www/ai_agency/ai_agency
source venv/bin/activate  # или путь к venv
pip install -r requirements.txt

# 5. Установить tmux (если нет)
which tmux || apt install -y tmux

# 6. Restart
systemctl restart ai-agency
systemctl status ai-agency
tail -f /var/log/ai-agency.log  # 30 sec, искать ошибки

# 7. Cron для rotate_backups
( crontab -l 2>/dev/null; \
  echo "0 4 * * * /var/www/ai_agency/ai_agency/scripts/rotate_backups.sh >> /var/log/ai-agency-rotate.log 2>&1" \
) | crontab -

# 8. Smoke-test в браузере: http://89.22.235.144/hq/login.html
# Логин: owner / WMhA3aejzKjk03OHez8iSjtV (новый ADMIN_PASSWORD)
```

---

## Подробный план

### 0. Предусловия

- SSH доступ к `89.22.235.144` от `root` (или sudo)
- Git клонирован на сервере, или WinSCP готов
- Знание текущего пути приложения: `/var/www/ai_agency/ai_agency/` (по `CLAUDE.md`)

### 1. Backup (КРИТИЧНО — не пропускать)

На сервере:

```bash
TS=$(date +%Y%m%d_%H%M%S)

# Полный snapshot файлов
tar -czf /tmp/ai_agency_pre_v1.0_${TS}.tar.gz -C /var/www ai_agency
ls -lh /tmp/ai_agency_pre_v1.0_${TS}.tar.gz   # обычно ~100-200 MB

# Отдельная копия БД
cp /var/www/ai_agency/ai_agency/agency.db /tmp/agency_pre_v1.0_${TS}.db
```

Если что-то пойдёт не так:
```bash
systemctl stop ai-agency
tar -xzf /tmp/ai_agency_pre_v1.0_${TS}.tar.gz -C /var/www
cp /tmp/agency_pre_v1.0_${TS}.db /var/www/ai_agency/ai_agency/agency.db
systemctl start ai-agency
```

### 2. Перенос файлов

Два варианта:

#### Вариант A: git (рекомендуется)

Если на сервере репозиторий уже клонирован:
```bash
cd /var/www/ai_agency
git fetch origin
git status   # должен быть clean
git pull origin main
```

Если нет — клонировать заново (потребуется SSH key для GitHub):
```bash
cd /tmp
git clone git@github.com:NickolasCage52/HQ_Panel.git ai_agency_new
# Скопировать содержимое БЕЗ .env и agency.db в /var/www/ai_agency
rsync -av --exclude='.env' --exclude='agency.db' --exclude='backups/' --exclude='venv/' /tmp/ai_agency_new/ /var/www/ai_agency/
rm -rf /tmp/ai_agency_new
```

#### Вариант B: WinSCP

С локальной машины (Windows) — открыть WinSCP, в `/var/www/ai_agency/` загрузить:

**Изменённые/новые файлы Sprint 1-5:**
- `ai_agency/.env` (с новыми токенами и ADMIN_PASSWORD — см. §3)
- `ai_agency/.env.example`
- `ai_agency/database.py`
- `ai_agency/api.py`
- `ai_agency/hq_v3_api.py`
- `ai_agency/main.py`
- `ai_agency/session_store.py` (НОВЫЙ)
- `ai_agency/pipeline_api.py` (НОВЫЙ)
- `ai_agency/pipeline/` (вся папка, НОВАЯ)
- `ai_agency/static/hq/_components.js` (sidebar)
- `ai_agency/static/hq/pipeline.html` (НОВЫЙ)
- `ai_agency/static/hq/pipeline-run-detail.html` (НОВЫЙ)
- `ai_agency/static/hq/hq-pipeline.js` (НОВЫЙ)
- `ai_agency/scripts/rotate_backups.sh` (НОВЫЙ, не забыть `chmod +x` после загрузки)
- `ai_agency/static/admin/DEPRECATED.md` (НОВЫЙ, marker)
- `ai_agency/CLAUDE.md` (обновлён)
- `ai_agency/OWNER_GUIDE.md` (обновлён)
- `ai_agency/requirements.txt` (новые deps)
- `ai_agency/tests/test_pipeline_skeleton.py` (НОВЫЙ)
- `ai_agency/tests/test_pipeline_phases_1_4.py` (НОВЫЙ, skipif)
- `ai_agency/tests/test_pipeline_e2e.py` (НОВЫЙ, skipif)
- `agency/standards/` (вся папка, НОВАЯ — landing.md + skills/)
- `docs/` (вся папка, НОВАЯ — все reports + plans + backlog)
- `01_AGENTS/DEPRECATED.md` (НОВЫЙ, marker)
- `scripts/DEPRECATED.md` (НОВЫЙ, marker)
- `.gitignore` (НОВЫЙ)
- `README.md` (НОВЫЙ)

**НЕ загружать:** `ai_agency/agency.db` (используем существующий на проде), `ai_agency/venv/`, `ai_agency/__pycache__/`, `ai_agency/data/knowledge/` (не трогаем).

### 3. Обновить `.env` на проде

КЛЮЧЕВЫЕ изменения (по результатам Sprint 1):

```env
# ANTHROPIC: ОТОЗВАН в Sprint 1, поставить placeholder
ANTHROPIC_API_KEY=disabled-not-used
# CLAUDE_MODEL/DEFAULT_TASK_MODE остаются прежние

# Telegram: оставлен СТАРЫЙ токен по решению владельца (Sprint 1 T-1-007 deferred)
# TELEGRAM_BOT_TOKEN=… (без изменений)

# ADMIN_PASSWORD: НОВЫЙ
ADMIN_PASSWORD=WMhA3aejzKjk03OHez8iSjtV

# SECRET_KEY: НОВЫЙ — сгенерировать на сервере или взять из локального .env
# Если генерируешь на сервере:
#   openssl rand -hex 32
SECRET_KEY=<новое 64-hex значение>

# Остальное (HOST, PORT, AUTO_PUBLISH, TIMEZONE, YANDEX_*) — без изменений
```

⚠ **Важно:** не используй ту же `SECRET_KEY` что в локальном `.env` — это файл с секретами, на проде должен быть отдельный.

### 4. Обновить зависимости

```bash
cd /var/www/ai_agency/ai_agency
source venv/bin/activate
pip install -r requirements.txt --upgrade-strategy only-if-needed
```

Новые пакеты которые подтянутся:
- `claude-agent-sdk>=0.2.0,<1`
- `GitPython>=3.1.0`
- Транзитивные обновления: `fastapi 0.110 → 0.136`, `uvicorn 0.27 → 0.47`, `starlette → 1.0`, `pydantic → 2.13+`
- `mcp` (transitive от claude-agent-sdk), `pyjwt[crypto]`, `cryptography`

Проверить что нет ошибок: `python -c "import fastapi, claude_agent_sdk, git; print('OK')"`.

### 5. tmux (если ещё не установлен)

```bash
which tmux || apt install -y tmux
tmux -V
```

### 6. Сделать `rotate_backups.sh` исполняемым

```bash
chmod +x /var/www/ai_agency/ai_agency/scripts/rotate_backups.sh
```

### 7. Restart

```bash
systemctl restart ai-agency
systemctl status ai-agency   # должно быть active (running)
tail -f /var/log/ai-agency.log
```

В логе ожидаются:
- `AI Agency Management System`
- `Бэкап БД создан: …`
- `База данных инициализирована`
- `Migration: …` несколько раз
- `Pipeline tables ready (pipeline_runs, _sprints, _events, _chat_messages, _rate_limits)` ← новое
- `База данных готова`
- `Pipeline Telegram watcher started (background task)` ← новое
- Список 23 агентов
- `[API] http://0.0.0.0:8000`

Если есть **ERROR** или **CRITICAL** — стоп, разбираться. Не оставлять сервис в broken state.

### 8. Cron для rotate_backups

```bash
( crontab -l 2>/dev/null; \
  echo "0 4 * * * /var/www/ai_agency/ai_agency/scripts/rotate_backups.sh >> /var/log/ai-agency-rotate.log 2>&1" \
) | crontab -

crontab -l | grep rotate_backups   # проверить что запись есть
```

### 9. Smoke-test в браузере

С локальной машины:

1. Открыть **http://89.22.235.144/hq/login.html**
2. Логин: `owner`
3. Пароль: `WMhA3aejzKjk03OHez8iSjtV` (новый ADMIN_PASSWORD)
4. Перейти на дашборд → должна загрузиться без ошибок
5. В sidebar должен быть пункт «🤖 AI Pipeline» (для роли owner)
6. Click на «AI Pipeline» → открывается `pipeline.html` с пустым списком и кнопкой «+ Новый pipeline-run»
7. Не нажимать «Запустить» сейчас (без `ANTHROPIC_API_KEY` пайплайн пройдёт stub-фазы за ~14 сек)
8. Открыть «AI Команда (legacy)» — должна работать визуально, при попытке чата выдаст ошибку Anthropic (это нормально, ключ отозван)
9. Проверить «Производство» (delivery.html) — карточки проектов должны отображаться

### 10. Telegram-бот

```bash
# Бот должен быть запущен (если не WEB_ONLY)
# Проверить:
journalctl -u ai-agency --since "2 minutes ago" | grep -i "telegram\|bot"
# Должно быть что-то типа "Telegram bot started" или "polling"
```

В Telegram → найти бота (по новому/старому токену) → /start → должен ответить.

### 11. Проверить новый pipeline E2E (опционально, stub mode)

С локальной машины:

```powershell
# Получить токен (или использовать тот что в browser localStorage)
$resp = Invoke-RestMethod -Uri "http://89.22.235.144/api/auth/login" -Method POST -Body '{"login":"owner","password":"WMhA3aejzKjk03OHez8iSjtV"}' -ContentType "application/json"
$token = $resp.token

# Создать stub-run (на проде не будет stub-mode т.к. PIPELINE_FORCE_STUB не установлен,
# но без ключа Phase 1 упадёт с ClaudeCodeError — что тоже OK для smoke)
Invoke-RestMethod -Uri "http://89.22.235.144/api/pipeline/runs" -Method POST -Headers @{"X-Auth-Token"=$token} -ContentType "application/json" -Body '{"title":"smoke","raw_idea":"test","project_type":"landing","autonomy_level":3,"deploy_strategy":"none"}'
# → 201 + run_id

# Подождать 5 сек, проверить статус
Start-Sleep -Seconds 5
Invoke-RestMethod -Uri "http://89.22.235.144/api/pipeline/runs/<id>" -Headers @{"X-Auth-Token"=$token}
# → status должен быть "running" (потом "failed" из-за нет ключа), либо "done" если отрабатывает быстро
```

Это smoke pipeline — главное что endpoint отвечает 201, в БД создаётся row.

### 12. Если что-то сломалось

```bash
# Посмотреть последние 100 строк лога с ошибками
tail -100 /var/log/ai-agency.log | grep -i "error\|critical\|traceback"

# Посмотреть status
systemctl status ai-agency

# Откат
systemctl stop ai-agency
tar -xzf /tmp/ai_agency_pre_v1.0_<TS>.tar.gz -C /var/www
cp /tmp/agency_pre_v1.0_<TS>.db /var/www/ai_agency/ai_agency/agency.db
systemctl start ai-agency
```

## Что после deploy

1. **GitHub Release v1.0.0** — открыть https://github.com/NickolasCage52/HQ_Panel/releases/new
   - Tag: `v1.0.0` (уже создан и запушен)
   - Title: `AI Pipeline Module v1.0.0`
   - Description: copy from `docs/sprint-5-final-report.md`

2. **Активация Claude skills** на твоей dev-машине (для будущей real Phase 1-4 работы):

   ```powershell
   $skills = "$env:USERPROFILE\.claude\skills"
   New-Item -ItemType Directory -Force -Path "$skills\prd-builder","$skills\architecture-decider","$skills\sprint-planner" | Out-Null
   Copy-Item "agency\standards\skills\prd-builder.md"        "$skills\prd-builder\SKILL.md"
   Copy-Item "agency\standards\skills\architecture-decider.md" "$skills\architecture-decider\SKILL.md"
   Copy-Item "agency\standards\skills\sprint-planner.md"     "$skills\sprint-planner\SKILL.md"
   ```

3. **Тест real Phase 1-4** (опционально, требует ANTHROPIC_API_KEY восстановить):
   - В `.env` поставить реальный ключ
   - `pytest ai_agency/tests/test_pipeline_phases_1_4.py -v -s` — должен пройти за 10-20 минут

## Известные риски

- **Force-logout всех:** после restart все текущие HQ-сессии перестают работать (in-memory `_sessions` не было персистентно до Sprint 1; теперь в БД, но именно при первом deploy таблица только создаётся).
- **AI-чат в team.html сломается** (намеренно — `ANTHROPIC_API_KEY=disabled-not-used`).
- **`/agent` команда в Telegram** — упадёт с ошибкой Claude API (graceful, не падает бот).
- **Любой текстовый chat в Telegram → orchestrator → Claude** — то же.

Эти три пункта — ожидаемое поведение Sprint 1 решения. Они отвалятся пока key не восстановят.

## Где смотреть когда работает

- HQ панель: http://89.22.235.144/hq/
- Pipeline UI: http://89.22.235.144/hq/pipeline.html
- API: http://89.22.235.144/api/pipeline/runs (с X-Auth-Token)
- Логи: `tail -f /var/log/ai-agency.log` и `/var/log/ai-agency-error.log`
- БД (read-only): `sqlite3 /var/www/ai_agency/ai_agency/agency.db ".tables"`
- Бэкапы: `ls -lh /var/www/ai_agency/ai_agency/backups/`
