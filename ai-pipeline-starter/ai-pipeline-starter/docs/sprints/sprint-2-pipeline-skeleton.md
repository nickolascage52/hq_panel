# Sprint 2: Pipeline Skeleton

**Цель:** собрать каркас pipeline-модуля без реальной интеграции с Claude Code SDK. После этого спринта через API можно создать pipeline-run, увидеть его в БД, получить события через WebSocket — но реального выполнения ещё нет.

**Длительность:** 3-4 дня по 2-3 часа.

**Зависимости:** Sprint 1 завершён.

---

## Задачи

### T-2-001: Проверка совместимости claude-agent-sdk с anthropic<1

**Type:** research
**Files:** —
**Acceptance:**
- В отдельной virtualenv установить:
  ```bash
  python -m venv /tmp/test_sdk
  source /tmp/test_sdk/bin/activate
  pip install claude-agent-sdk anthropic>=0.40,<1
  ```
- Запустить минимальный пример SDK
- Если есть конфликт зависимостей — задокументировать в `docs/dependency-decisions.md`
- Решить: либо downgrade SDK, либо upgrade anthropic, либо отдельное окружение для pipeline
- Финальная запись в `docs/dependency-decisions.md` с выбором

**Estimate:** M (30-60 минут)
**Depends-on:** —

---

### T-2-002: Установить claude-agent-sdk и GitPython

**Type:** setup
**Files:** `ai_agency/requirements.txt`
**Acceptance:**
- Решение из T-2-001 применено
- В `requirements.txt` добавлено:
  ```
  claude-agent-sdk>=<выбранная-версия>
  GitPython>=3.1.0
  ```
- `pip install -r requirements.txt` проходит локально
- Закоммитить

**Estimate:** S (15 минут)
**Depends-on:** T-2-001

---

### T-2-003: Создать структуру pipeline/ модуля

**Type:** setup
**Files:** `ai_agency/pipeline/` (новая папка) с пустыми файлами
**Acceptance:**
- Создана структура:
  ```
  ai_agency/pipeline/
  ├── __init__.py                # exports + resume_pending_runs()
  ├── runner.py                  # PipelineRunner
  ├── workspace.py               # PipelineWorkspace
  ├── progress.py                # PipelineProgress
  ├── exceptions.py              # PipelineError, RateLimitExceeded, etc.
  ├── claude_runner.py           # stub
  ├── tmux_manager.py            # stub
  ├── git_manager.py             # stub
  ├── rate_limit.py              # stub
  ├── queue.py                   # stub
  └── phases/
      ├── __init__.py
      ├── base.py                # PhaseBase abstract class
      ├── phase1_prompt.py       # stub
      ├── phase2_prd.py          # stub
      ├── phase3_architecture.py # stub
      ├── phase4_sprints.py      # stub
      ├── phase5_execution.py    # stub
      ├── phase6_validation.py   # stub
      └── phase7_handoff.py      # stub
  ```
- Каждый stub-файл содержит docstring с описанием класса/функции и `pass`/`raise NotImplementedError`
- Закоммитить

**Estimate:** M (30 минут)
**Depends-on:** T-2-002

---

### T-2-004: Создать миграцию pipeline_* таблиц

**Type:** feature
**Files:** `ai_agency/database.py`
**Acceptance:**
- Добавлена функция `_add_pipeline_tables(db)` в `database.py`:
  - `pipeline_runs` (схема из ARCHITECTURE.md раздел 5.1)
  - `pipeline_sprints` (5.2)
  - `pipeline_events` (5.3)
  - `pipeline_chat_messages` (5.4)
  - `pipeline_rate_limits` (5.5)
- Включая все индексы из ARCHITECTURE.md
- Включая seed для `pipeline_rate_limits` (3 строки: opus, sonnet, haiku)
- Вызов из `init_db()` в правильном порядке
- Запустить локально, миграция применилась
- Проверить: `sqlite3 agency.db ".tables" | grep pipeline`
- Проверить: `sqlite3 agency.db "SELECT * FROM pipeline_rate_limits"`

**Estimate:** L (60-90 минут)
**Depends-on:** T-2-002

---

### T-2-005: Включить SQLite WAL mode

**Type:** feature
**Files:** `ai_agency/database.py` (в `init_db` или в connection setup)
**Acceptance:**
- При подключении к БД выполняется `PRAGMA journal_mode=WAL`
- При подключении выполняется `PRAGMA synchronous=NORMAL` (для перформанса с WAL)
- Проверка: `sqlite3 agency.db "PRAGMA journal_mode"` показывает `wal`
- E2E: запустить приложение, сделать несколько одновременных запросов — нет database is locked

**Estimate:** S (20 минут)
**Depends-on:** T-2-004

---

### T-2-006: Реализовать pipeline/exceptions.py

**Type:** feature
**Files:** `ai_agency/pipeline/exceptions.py`
**Acceptance:**
- Базовый класс `PipelineError(Exception)`
- Подклассы:
  - `RateLimitExceeded(PipelineError)` с полем `resume_after`
  - `WorkspaceError(PipelineError)`
  - `PhaseExecutionError(PipelineError)` с полем `phase_name`
  - `ApprovalRequired(PipelineError)` с полем `phase_name`
  - `ClaudeCodeError(PipelineError)` с полем `agent_persona`
  - `GitError(PipelineError)`
- Закоммитить

**Estimate:** S (15 минут)
**Depends-on:** T-2-003

---

### T-2-007: Реализовать PipelineWorkspace

**Type:** feature
**Files:** `ai_agency/pipeline/workspace.py`
**Acceptance:**
- Класс `PipelineWorkspace(run_id: int)`
- Методы:
  - `path` — property, возвращает путь `/var/www/ai_agency/pipeline_workspaces/<run_id>/`
  - `create()` — создаёт директорию, инициализирует git repo, копирует шаблон CLAUDE.md и .claude/agents/ из `agency/standards/` если есть
  - `exists()` — bool
  - `cleanup()` — удаляет директорию (для abort)
  - `docs_path` — путь к `docs/`
- E2E:
  - `ws = PipelineWorkspace(999)`
  - `await ws.create()`
  - Проверить что `/var/www/ai_agency/pipeline_workspaces/999/.git/` существует
  - `await ws.cleanup()`
  - Директории больше нет

**Estimate:** M (60 минут)
**Depends-on:** T-2-006

---

### T-2-008: Реализовать PipelineProgress

**Type:** feature
**Files:** `ai_agency/pipeline/progress.py`
**Acceptance:**
- Класс `PipelineProgress(run_id, db)`
- Методы:
  - `emit_event(event_type, payload, sprint_id=None, task_id=None, severity='info')` — пишет в `pipeline_events` + WebSocket broadcast
  - Подписчики хранятся в глобальном `_subscribers: dict[run_id, list[WebSocket]]`
  - `subscribe(websocket)`, `unsubscribe(websocket)`
- Паттерн копируется с существующего `TaskProgress` из `orchestrator.py`
- Закоммитить

**Estimate:** M (60 минут)
**Depends-on:** T-2-004

---

### T-2-009: Реализовать PipelineRunner (skeleton)

**Type:** feature
**Files:** `ai_agency/pipeline/runner.py`
**Acceptance:**
- Класс `PipelineRunner(run_id, db)`
- Метод `async def execute()` который:
  - Загружает run из БД
  - Создаёт workspace
  - Итерирует через phases (но фазы пока stub, просто меняют статус)
  - Записывает события в `pipeline_progress`
- Метод `async def resume()` — продолжает с current_phase
- Обработка `RateLimitExceeded` → pause
- Обработка `PhaseExecutionError` → mark failed
- E2E: создать запись в БД руками, вызвать `PipelineRunner(id).execute()`, увидеть события в `pipeline_events`

**Estimate:** L (90 минут)
**Depends-on:** T-2-007, T-2-008

---

### T-2-010: Реализовать PhaseBase и stub-фазы

**Type:** feature
**Files:** `ai_agency/pipeline/phases/*.py`
**Acceptance:**
- `PhaseBase` abstract класс с методом `async execute(runner) -> None`
- Каждая phase1-7 наследует, но просто:
  - Записывает в pipeline_events что фаза стартанула
  - Спит 2 секунды (для имитации работы)
  - Записывает что фаза завершилась
- Это позволяет протестировать оркестрацию без реальной работы

**Estimate:** M (60 минут)
**Depends-on:** T-2-006

---

### T-2-011: Создать pipeline_api.py

**Type:** feature
**Files:** `ai_agency/pipeline_api.py` (новый), `ai_agency/main.py` (модификация)
**Acceptance:**
- Файл `pipeline_api.py` создан по образцу `hq_v3_api.py`
- Функция `register_pipeline_routes(app: FastAPI)` навешивает эндпоинты
- В `main.py` добавлен импорт и вызов:
  ```python
  from pipeline_api import register_pipeline_routes
  register_pipeline_routes(app)
  ```
- Минимальные эндпоинты:
  - `POST /api/pipeline/runs` — создаёт запись в pipeline_runs, запускает PipelineRunner в asyncio
  - `GET /api/pipeline/runs` — список с filters
  - `GET /api/pipeline/runs/{id}` — детали
  - `GET /api/pipeline/runs/{id}/events?limit=50&since=` — события
- Все эндпоинты защищены `require_role(['owner'])`
- E2E через curl/Postman:
  - `POST /api/pipeline/runs` с `{title, raw_idea, project_type, autonomy_level, deploy_strategy}` → 201, run_id
  - `GET /api/pipeline/runs/{id}` → детали
  - Через 5-10 секунд `GET /api/pipeline/runs/{id}/events` → видно как phases прошли

**Estimate:** L (90 минут)
**Depends-on:** T-2-009, T-2-010

---

### T-2-012: WebSocket /ws/pipeline/{run_id}

**Type:** feature
**Files:** `ai_agency/pipeline_api.py`
**Acceptance:**
- Эндпоинт `WebSocket /ws/pipeline/{run_id}`
- Аутентификация через query parameter `?token=`
- При коннекте — `subscribe` в `PipelineProgress._subscribers[run_id]`
- Стримит события в формате `{"event_type": "...", "payload": {...}, "timestamp": "..."}`
- При дисконнекте — `unsubscribe`
- E2E:
  - В одном терминале подключиться к ws (через `websocat` или JS клиент)
  - В другом терминале — `POST /api/pipeline/runs`
  - В ws видны события phases в реальном времени

**Estimate:** M (45 минут)
**Depends-on:** T-2-011

---

### T-2-013: resume_pending_runs на старте

**Type:** feature
**Files:** `ai_agency/pipeline/__init__.py`, `ai_agency/main.py`
**Acceptance:**
- Функция `async resume_pending_runs(db)`:
  - SELECT pipeline_runs WHERE status IN ('running', 'paused_rate_limit')
  - Для каждого:
    - Если paused_rate_limit и resume_after < now() — запустить PipelineRunner.resume()
    - Если running — был прерван рестартом, тоже resume
- Вызов в `main.py` после `init_db()`:
  ```python
  asyncio.create_task(resume_pending_runs(db))
  ```
- E2E:
  - Запустить pipeline через API
  - Через 5 секунд (когда run в середине фаз) — `Ctrl+C` сервер
  - Запустить заново — run должен продолжиться

**Estimate:** M (45 минут)
**Depends-on:** T-2-011

---

### T-2-014: E2E test для pipeline-runs

**Type:** test
**Files:** `ai_agency/tests/test_pipeline_skeleton.py` (новый)
**Acceptance:**
- Тест:
  1. Создать pipeline-run через `POST /api/pipeline/runs`
  2. Подождать 30 секунд (все 7 фаз x 2 сек спит каждая)
  3. `GET /api/pipeline/runs/{id}` — status='done', current_phase='handoff'
  4. `GET /api/pipeline/runs/{id}/events` — 14 событий (по 2 на фазу: started, completed)
- Запустить тест: `python -m pytest tests/test_pipeline_skeleton.py -v`
- Должен пройти

**Estimate:** M (45 минут)
**Depends-on:** T-2-013

---

## Definition of done for sprint 2

- [ ] Все задачи T-2-001..T-2-014 выполнены
- [ ] `claude-agent-sdk` установлен, совместимость подтверждена
- [ ] Все pipeline_* таблицы в БД, WAL mode включён
- [ ] PipelineRunner с stub-фазами работает
- [ ] API создаёт run, list, get, events
- [ ] WebSocket стримит события
- [ ] Resume после рестарта работает
- [ ] E2E test проходит

## Acceptance demo

После Sprint 2:

1. `curl -X POST localhost:8000/api/pipeline/runs -H "X-Auth-Token: ..." -d '{"title":"test","raw_idea":"Простой landing","project_type":"landing","autonomy_level":2,"deploy_strategy":"none"}'` → 201, run_id
2. В отдельном терминале `websocat ws://localhost:8000/ws/pipeline/<id>?token=...` — стрим событий
3. Через 30 секунд run завершён
4. `GET /api/pipeline/runs/<id>/events` показывает 14 событий

## Что НЕ делаем в Sprint 2

- НЕ интегрируемся с Claude Code SDK (фазы пока stub)
- НЕ создаём UI (это Sprint 4)
- НЕ трогаем старую AI Команду
- НЕ реализуем rate_limit logic (только stub)
- НЕ реализуем git_manager (только stub)
