# ARCHITECTURE: AI Pipeline Module

**Дата:** 2026-05-15
**Связан с:** `docs/PRD.md`, `docs/audit-2026-05-15.md`

---

## 1. Архитектурные принципы

1. **Дополняем, не переписываем.** Pipeline — новый модуль `pipeline/` рядом с `agents/`, не вместо. Старая AI Команда работает параллельно.
2. **Переиспользуем существующее.** `delivery_*` таблицы, `executors`, `agent_executions`, WebSocket-паттерн, auth-слой — всё это уже есть и работает.
3. **Изоляция новой логики.** Pipeline получает свой подмодуль, свой API namespace (`/api/pipeline/*`), свою БД-таблицу для специфичного состояния, свой UI-раздел.
4. **State в БД, не в памяти.** Pipeline-run может длиться часами и переживать рестарты. Никакого in-memory state.
5. **Async-first.** Pipeline coordinator и agent management — асинхронные. Никаких блокирующих вызовов в event loop.
6. **Git-driven.** Каждый pipeline-run работает в отдельной git ветке (или worktree). Все изменения трекаются.

---

## 2. Стек (LOCKED)

| Слой | Технология | Версия | Обоснование |
|------|-----------|--------|-------------|
| Backend | FastAPI | 0.110.0 (existing) | Совместимость с api.py / hq_v3_api.py |
| Async | asyncio + aiosqlite | existing | Уже есть, не меняем |
| БД | SQLite + WAL mode | existing | Расширяется существующая `agency.db`. WAL включается для concurrency. |
| Claude integration | claude-agent-sdk | latest | Новая зависимость. Совместимость с `anthropic>=0.40,<1` — проверить в Sprint 2 |
| Process management | tmux + asyncio.subprocess | tmux 3.x | tmux уже используется в проекте (папка `10_TMUX/`) |
| Git operations | GitPython или subprocess | latest | GitPython проще для асинхронной обёртки |
| WebSocket | FastAPI WebSocket | existing | Паттерн уже работает в `/ws/task/{id}` |
| Frontend | Vanilla JS + CSS | existing | Соответствие существующему стеку HQ |
| HTTP client (для GitHub API) | httpx | 0.27.0 (existing) | Уже в requirements |

**Запрещено в этом модуле:**
- React/Vue/Svelte (несовместимо со стеком фронта)
- Postgres/Redis (без них пока обходимся, не усложняем инфру)
- Celery/RQ (используем asyncio + БД для очереди)
- Прямые `messages.create()` Anthropic (всё через claude-agent-sdk для consistency)

---

## 3. Структура файлов

### 3.1 Что добавляется в `ai_agency/`

```
ai_agency/
├── pipeline/                          # ← НОВОЕ
│   ├── __init__.py
│   ├── runner.py                      # PipelineRunner — главный координатор
│   ├── phases/                        # каждая фаза отдельным файлом
│   │   ├── __init__.py
│   │   ├── phase1_prompt.py
│   │   ├── phase2_prd.py
│   │   ├── phase3_architecture.py
│   │   ├── phase4_sprints.py
│   │   ├── phase5_execution.py
│   │   ├── phase6_validation.py
│   │   └── phase7_handoff.py
│   ├── claude_runner.py               # обёртка над claude-agent-sdk
│   ├── tmux_manager.py                # управление tmux сессиями
│   ├── git_manager.py                 # init repo, worktree, commits, push
│   ├── rate_limit.py                  # отслеживание лимитов и downgrade logic
│   ├── queue.py                       # очередь pipeline-runs
│   └── progress.py                    # PipelineProgress (аналог TaskProgress)
│
├── pipeline_api.py                    # ← НОВОЕ: эндпоинты /api/pipeline/*
│                                       #   навешивается на app как hq_v3_api.py
│
├── pipeline_workspaces/               # ← НОВОЕ: workspaces для pipeline-runs
│   └── <run_id>/                      # git worktree + docs + .claude/
│       ├── docs/PRD.md
│       ├── docs/ARCHITECTURE.md
│       ├── docs/sprints/
│       ├── CLAUDE.md
│       ├── .claude/agents/
│       └── (генерируемый код проекта клиента)
│
└── static/hq/
    ├── pipeline.html                  # ← НОВОЕ: список и создание pipeline-runs
    ├── pipeline-run-detail.html       # ← НОВОЕ: детали конкретного run
    └── (никакие существующие файлы не меняются в этом sprint)
```

### 3.2 Что меняется в существующем коде

| Файл | Изменение |
|------|-----------|
| `database.py` | Добавляются новые таблицы (см. раздел 5). НЕ переписывается, только дополняется в `init_db()`. |
| `main.py` | Добавляется `from pipeline_api import register_pipeline_routes; register_pipeline_routes(app)` |
| `static/hq/_components.js` | В `SIDEBAR_ITEMS` добавляется пункт `{label: 'AI Pipeline', path: 'pipeline.html', icon: 'robot', roles: ['owner']}` |
| `requirements.txt` | Добавляется `claude-agent-sdk`, `GitPython` |
| `.gitignore` | Создаётся с нуля в Sprint 1 |

Никакие другие существующие файлы в Sprint 1-4 не меняются. Старый `orchestrator.py`, `agents/`, `telegram_bot.py` — НЕ ТРОГАЕМ до Sprint 5.

---

## 4. Архитектура pipeline lifecycle

### 4.1 Главный цикл (PipelineRunner)

```python
# pipeline/runner.py — схема, не финальный код

class PipelineRunner:
    def __init__(self, run_id: int, db: aiosqlite.Connection):
        self.run_id = run_id
        self.db = db
        self.workspace = PipelineWorkspace(run_id)
        self.progress = PipelineProgress(run_id)
        self.rate_limit = RateLimitManager()
        self.tmux = TmuxManager(run_id)

    async def execute(self):
        try:
            phases = [Phase1Prompt, Phase2PRD, Phase3Architecture,
                      Phase4Sprints, Phase5Execution, Phase6Validation,
                      Phase7Handoff]
            for phase_cls in phases:
                await self._check_rate_limit_or_pause()
                if await self._should_pause_for_approval(phase_cls):
                    await self._mark_awaiting_approval(phase_cls)
                    return
                phase = phase_cls(self)
                await phase.execute()
                await self._mark_phase_done(phase_cls)
        except RateLimitExceeded as e:
            await self._pause_for_rate_limit(e)
        except PipelineError as e:
            await self._mark_failed(e)
```

### 4.2 Запуск pipeline (entry point)

```
POST /api/pipeline/runs (FastAPI handler)
  └─ Создаёт pipeline_runs запись (status='pending')
  └─ Создаёт delivery_project (если нет)
  └─ Создаёт workspace на диске
  └─ asyncio.create_task(PipelineRunner(...).execute())
  └─ Возвращает 201 с run_id
```

Долгая задача живёт в asyncio. Состояние пишется в БД, прогресс — через WebSocket и Telegram.

### 4.3 Резюме после рестарта

При старте `main.py`:
```python
# pipeline/__init__.py — на старте
async def resume_pending_runs():
    runs = await db.execute_fetchall(
        "SELECT id FROM pipeline_runs WHERE status IN ('running', 'paused_rate_limit')"
    )
    for run in runs:
        if run.status == 'paused_rate_limit' and run.resume_after < now():
            asyncio.create_task(PipelineRunner(run.id, db).execute())
        elif run.status == 'running':
            # был активный run, рестарт прервал — продолжаем с последней успешной фазы
            asyncio.create_task(PipelineRunner(run.id, db).resume())
```

---

## 5. БД-схема: новые таблицы

Все таблицы создаются через `_add_pipeline_migration()` в `database.py:init_db()` (идемпотентно).

### 5.1 `pipeline_runs` — главная сущность

```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_project_id INTEGER REFERENCES delivery_projects(id),  -- FK
    title TEXT NOT NULL,
    raw_idea TEXT NOT NULL,                       -- что пользователь ввёл
    production_prompt TEXT,                       -- после /prompt-forge
    project_type TEXT NOT NULL,                   -- landing|telegram_bot|n8n|ai_assistant|custom
    autonomy_level INTEGER NOT NULL DEFAULT 2,    -- 1, 2, 3
    deploy_strategy TEXT NOT NULL DEFAULT 'none', -- none|vercel|aeza|custom

    status TEXT NOT NULL DEFAULT 'pending',
    -- pending | running | paused_user | paused_rate_limit | awaiting_approval
    -- | validating | deploying | review | done | failed | aborted

    current_phase TEXT,                           -- prompt|prd|architecture|sprints|execution|validation|handoff
    current_sprint_id INTEGER,                    -- FK pipeline_sprints (создаётся в Phase 4)

    workspace_path TEXT,                          -- /var/www/.../pipeline_workspaces/<id>/
    tmux_session_name TEXT,                       -- pipeline-run-<id>
    git_branch TEXT,                              -- pipeline/<id>-<slug>
    github_repo_url TEXT,                         -- куда пушим (если есть)

    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    pause_reason TEXT,
    resume_after TIMESTAMP,                       -- когда auto-resume (для rate limit)
    completed_at TIMESTAMP,

    initiated_by INTEGER REFERENCES hq_users(id),
    error_message TEXT,                           -- если failed

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_delivery_project ON pipeline_runs(delivery_project_id);
```

### 5.2 `pipeline_sprints` — спринты в Phase 4

```sql
CREATE TABLE IF NOT EXISTS pipeline_sprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    delivery_stage_id INTEGER REFERENCES delivery_stages(id),  -- зеркалит в delivery_stages
    sprint_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    goal TEXT,
    spec_md TEXT,                                 -- содержимое sprint-N.md

    status TEXT NOT NULL DEFAULT 'planned',
    -- planned | active | validating | done | failed

    tasks_total INTEGER DEFAULT 0,
    tasks_done INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, sprint_number)
);
```

**Примечание про `delivery_stages`:** для каждого pipeline-sprint создаётся зеркальная запись в `delivery_stages` — это даёт нам бесплатное отображение в существующем `project-detail.html`. Pipeline-логика — в `pipeline_sprints`, отображение в HQ — через `delivery_stages`.

### 5.3 `pipeline_events` — лента событий

```sql
CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    sprint_id INTEGER REFERENCES pipeline_sprints(id),
    delivery_task_id INTEGER REFERENCES delivery_tasks(id),

    event_type TEXT NOT NULL,
    -- phase_started | phase_completed | task_started | task_done | task_failed
    -- | commit | pr_created | rate_limit_hit | paused | resumed
    -- | approval_needed | user_directive | telegram_sent | error

    severity TEXT DEFAULT 'info',                 -- info | warning | error
    payload_json TEXT,                            -- детали события
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_run ON pipeline_events(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_type ON pipeline_events(event_type);
```

### 5.4 `pipeline_chat_messages` — чат с pipeline в контексте проекта

```sql
CREATE TABLE IF NOT EXISTS pipeline_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                           -- user | orchestrator | agent_result | system
    agent_name TEXT,                              -- для role='agent_result'
    content_md TEXT NOT NULL,
    metadata_json TEXT,                           -- какие инструменты вызывались, токены
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_chat_run ON pipeline_chat_messages(run_id, created_at);
```

### 5.5 `pipeline_rate_limits` — текущее состояние лимитов

```sql
CREATE TABLE IF NOT EXISTS pipeline_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL UNIQUE,                   -- 'opus' | 'sonnet' | 'haiku'
    tokens_used_weekly INTEGER DEFAULT 0,
    tokens_limit_weekly INTEGER,
    weekly_reset_at TIMESTAMP,
    tokens_used_session INTEGER DEFAULT 0,
    session_reset_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- seeded with 3 rows on init: opus, sonnet, haiku
```

### 5.6 `hq_sessions` — миграция с in-memory сессий (Sprint 1)

```sql
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
);

CREATE INDEX IF NOT EXISTS idx_hq_sessions_token ON hq_sessions(token);
CREATE INDEX IF NOT EXISTS idx_hq_sessions_expires ON hq_sessions(expires_at);
```

**Эту таблицу делаем первой в Sprint 1.** `hq_v3_api.py:_sessions` (in-memory dict) заменяется на запросы к этой таблице.

---

## 6. API endpoints (новые)

Все навешиваются в `pipeline_api.py` на тот же `app`, что и `hq_v3_api.py`. Префикс `/api/pipeline/`.

### 6.1 CRUD pipeline-runs

| Method | Path | Auth | Описание |
|--------|------|------|----------|
| POST | `/api/pipeline/runs` | owner | Создать новый pipeline-run |
| GET | `/api/pipeline/runs` | owner,pm | Список с фильтрами `?status=&limit=` |
| GET | `/api/pipeline/runs/{id}` | owner,pm | Детали |
| GET | `/api/pipeline/runs/{id}/events?limit=50&since=` | owner,pm | Лента событий |
| GET | `/api/pipeline/runs/{id}/sprints` | owner,pm | Список спринтов |
| GET | `/api/pipeline/runs/{id}/sprints/{sid}/tasks` | owner,pm | Задачи спринта |

### 6.2 Управление

| Method | Path | Auth | Описание |
|--------|------|------|----------|
| POST | `/api/pipeline/runs/{id}/approve` | owner | Утвердить текущую фазу, продолжить |
| POST | `/api/pipeline/runs/{id}/pause` | owner | Ручная пауза |
| POST | `/api/pipeline/runs/{id}/resume` | owner | Возобновление |
| POST | `/api/pipeline/runs/{id}/abort` | owner | Отмена (создаёт бэкап-ветку) |
| POST | `/api/pipeline/runs/{id}/directive` | owner | Послать сообщение в активную сессию |

### 6.3 Чат с pipeline

| Method | Path | Auth | Описание |
|--------|------|------|----------|
| GET | `/api/pipeline/runs/{id}/chat` | owner,pm | История чата |
| POST | `/api/pipeline/runs/{id}/chat` | owner | Отправить сообщение в чат |

### 6.4 Утилитарные

| Method | Path | Auth | Описание |
|--------|------|------|----------|
| GET | `/api/pipeline/rate-limits` | owner | Текущее состояние лимитов |
| GET | `/api/pipeline/queue` | owner | Очередь pipeline-runs |
| WS | `/ws/pipeline/{run_id}` | owner | Стриминг событий run-а |

---

## 7. Frontend архитектура

### 7.1 Новые страницы

**`pipeline.html`** — главная страница раздела:
- Кнопка «Новый pipeline-run»
- Список pipeline-runs с фильтрами по статусу
- Live-индикатор для running runs
- Mini-карточки с progress bar, текущей фазой, последним событием
- Раздел «Лимиты» с current state

**`pipeline-run-detail.html`** — детали одного run:
- Header: статус, прогресс, кнопки управления
- Вкладки:
  - **Overview** — текущая фаза, последние события, link на git/preview
  - **PRD/Architecture** — рендер markdown файлов из workspace
  - **Sprints** — kanban спринтов с задачами (используем существующий SortableJS)
  - **Chat** — переписка с pipeline
  - **Events** — полная лента событий

### 7.2 JS-модули

**`hq-pipeline.js`** — namespace `HQPipeline`:
- `createRun(data)`, `listRuns(filters)`, `getRun(id)`
- WebSocket connection к `/ws/pipeline/{id}`
- Live updates карточек и detail page

### 7.3 Изменения в существующих файлах

Только одно: добавить пункт в `SIDEBAR_ITEMS` в `_components.js`:
```javascript
{
  label: 'AI Pipeline',
  path: 'pipeline.html',
  icon: 'cpu',
  roles: ['owner']
}
```

---

## 8. Integration с claude-agent-sdk

### 8.1 Базовый pattern

```python
# pipeline/claude_runner.py — псевдокод

from claude_agent_sdk import ClaudeAgent, ClaudeCodeOptions

async def run_phase_agent(
    workspace_path: str,
    agent_persona: str,           # 'architect' | 'builder-fastapi' | etc.
    task_md: str,                 # инструкция
    model: str = 'opus',
    timeout: int = 1800
) -> AgentResult:
    options = ClaudeCodeOptions(
        cwd=workspace_path,
        model=f'claude-{model}-latest',
        # читает .claude/agents/<persona>.md из workspace
        agents=[agent_persona],
        # max_turns ограничивает loop
        max_turns=50,
    )
    async with ClaudeAgent(options=options) as agent:
        async for event in agent.query(task_md):
            await save_event_to_db(event)
            yield event
```

### 8.2 Spawn команды для спринта

```python
# pipeline/phases/phase5_execution.py — псевдокод

async def execute_sprint(sprint: PipelineSprint, runner: PipelineRunner):
    # 1. Создаём tmux session
    await runner.tmux.create_session(f'pipeline-{runner.run_id}-sprint-{sprint.sprint_number}')

    # 2. Spawn architect (первый, фиксирует контракт)
    architect_result = await run_phase_agent(
        workspace_path=runner.workspace.path,
        agent_persona='architect',
        task_md=sprint.spec_md + '\n\nЗафиксируй контракт типов перед стартом builders.',
        model='opus'
    )

    # 3. Spawn builders параллельно
    tasks_by_owner = sprint.tasks_by_owner()
    builder_tasks = [
        run_phase_agent(
            workspace_path=runner.workspace.worktree_for(owner),
            agent_persona=f'builder-{owner}',
            task_md=format_tasks(tasks),
            model='sonnet'  # downgrade-aware!
        )
        for owner, tasks in tasks_by_owner.items()
    ]
    builder_results = await asyncio.gather(*builder_tasks)

    # 4. Spawn validator
    validator_result = await run_phase_agent(
        workspace_path=runner.workspace.path,
        agent_persona='validator',
        task_md='Run build, tests, typecheck, lint. Report results.',
        model='haiku'
    )

    # 5. Merge worktrees → main sprint branch
    await runner.git.merge_worktrees(sprint.id)

    # 6. Post-sprint validation
    review_result = await run_phase_agent(..., 'code-reviewer', 'sonnet')
    prd_check = await run_phase_agent(..., 'prd-compliance-checker', 'opus')

    # 7. Commit + push
    await runner.git.commit_sprint(sprint)
```

---

## 9. Rate limit handling

### 9.1 Источник данных

Claude Code CLI имеет команду `/usage` которая показывает текущее потребление. Pipeline `rate_limit.py` парсит её вывод периодически и обновляет `pipeline_rate_limits` таблицу.

Альтернатива (если CLI не парсится): ловить `RateLimitError` от SDK и инкрементально обновлять оценку.

### 9.2 Downgrade logic

```python
# pipeline/rate_limit.py — псевдокод

async def select_model_for_task(task_type: str) -> str | None:
    state = await get_rate_limit_state()

    weights = {
        'architecture': ['opus', 'sonnet'],         # downgrade chain
        'building': ['sonnet', 'haiku'],
        'validation': ['haiku'],
        'review': ['sonnet', 'haiku'],
        'prd_check': ['opus', 'sonnet'],
    }

    for model in weights.get(task_type, ['sonnet']):
        if state[model].weekly_usage_pct < 80:
            return model

    return None  # all limits exhausted → pause

async def maybe_pause_for_rate_limit(runner: PipelineRunner):
    state = await get_rate_limit_state()
    if all(s.weekly_usage_pct > 90 for s in state.values()):
        await runner.pause(
            reason='rate_limit_exhausted',
            resume_after=min(s.weekly_reset_at for s in state.values())
        )
        await telegram_notify(f"🔋 Pipeline #{runner.run_id} paused, resume ~{...}")
```

---

## 10. Git strategy

### 10.1 Workspaces

Каждый pipeline-run = отдельная директория `pipeline_workspaces/<run_id>/`. Это **отдельный git-репозиторий** (или worktree от шаблона), не подкаталог основного `AI_Delivery_Team`.

### 10.2 Branching

```
main                                  ← основная ветка проекта клиента
├── pipeline/<run_id>-init             ← создаётся при старте run
├── pipeline/<run_id>-sprint-1         ← одна ветка на спринт
│   ├── (commit) [T-1-001] init project
│   ├── (commit) [T-1-002] add base layout
│   └── ...
└── pipeline/<run_id>-sprint-N
```

### 10.3 Worktrees для параллельной работы

Внутри спринта builders работают параллельно через worktrees:
```bash
git worktree add pipeline/<run_id>-sprint-N-frontend ../worktree-frontend
git worktree add pipeline/<run_id>-sprint-N-backend  ../worktree-backend
```

После окончания работы builders — orchestrator merge-ит worktrees в основную sprint-ветку.

### 10.4 Push policy

- Push на GitHub после каждого спринта (если `github_repo_url` задан).
- Никогда не push в main автоматически. Только в `pipeline/*` ветки.
- Финальный handoff = создание PR `pipeline/<run_id>-final → main` для ручного review.

---

## 11. Folder structure pipeline workspace

```
pipeline_workspaces/<run_id>/
├── .git/                              # отдельный repo
├── CLAUDE.md                          # роль pipeline проекта (генерируется из шаблона)
├── docs/
│   ├── prompt.md                      # production prompt
│   ├── PRD.md                         # сгенерированный PRD
│   ├── ARCHITECTURE.md
│   ├── sprints/
│   │   ├── _index.md
│   │   ├── sprint-1-*.md
│   │   └── ...
│   ├── overseer-log.md
│   └── final-report.md
├── .claude/
│   └── agents/                        # копируются из шаблона типа проекта
├── events/                            # JSON-события для event-bridge (если используем)
└── (генерируемый код проекта клиента — Next.js / bot / etc)
```

---

## 12. Что НЕ строим в v1

Out of scope, явно:

1. **Параллельные pipeline-runs** — в v1 один за раз. Очередь хранится в БД, по очереди обрабатывается.
2. **Multi-tenancy** — нет разделения клиентов с разными правами доступа к runs.
3. **GitHub OAuth для пользователей** — pipeline пушит от системного бот-аккаунта, привязка через `delivery_projects.github_repo_url`.
4. **Кастомные agent personas через UI** — фиксированный набор в `.claude/agents/`. Кастомизация через файлы.
5. **Биллинг tokens / расходов** — отдельная задача для будущего.
6. **Self-healing на serious errors** — если build падает 3+ раз, pipeline ставит на паузу для человека, не пытается героически чинить.

---

## 13. Зависимости и риски

### 13.1 Технические зависимости

- `claude-agent-sdk` — новый. Совместимость с `anthropic>=0.40,<1` проверяется в Sprint 2 (первая задача).
- `GitPython` — новый. Можно заменить на subprocess, если плохо работает.
- tmux на сервере — должен быть установлен. Проверка в Sprint 1.

### 13.2 Архитектурные риски

1. **SQLite WAL и async** — нужно тщательно тестировать. Если будут блокировки, fallback: pipeline-state в отдельную `pipeline.db` файл.
2. **Long-running asyncio tasks** — могут «течь» при ошибках. Нужно тщательное `try/finally` и graceful shutdown.
3. **WebSocket reconnect** — если фронт теряет соединение, нужно резюмировать с последнего event_id. Фишка для Sprint 4.

---

## 14. Конвенции кода

- **Python 3.13**, type hints везде в новом коде.
- **Async/await** — никаких блокирующих вызовов в event loop.
- **Imports**: stdlib → third-party → local (`from pipeline.X import Y`).
- **Logger**: `logger = logging.getLogger(__name__)` в начале каждого модуля.
- **Errors**: кастомные исключения в `pipeline/exceptions.py` (`PipelineError`, `RateLimitExceeded`, `WorkspaceError`, etc.).
- **DB queries**: через `aiosqlite`, никаких raw connection строк. Reuse `database.py` helpers если они есть.
- **Naming**:
  - Files: `snake_case.py`
  - Classes: `PascalCase`
  - Funcs/vars: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`

---

## 15. Точки расширения (после v1)

После того как v1 работает, естественные расширения:

- **Параллельные runs** — менеджер очереди + изолированные workspace
- **Deploy strategies** — добавление новых (Render, Railway, Fly.io)
- **Custom templates** — UI для редактирования `agency/standards/<type>.md`
- **Cost tracking** — точный учёт токенов по run-у в `pipeline_rate_limits`
- **Agent versioning** — версионирование `.claude/agents/*.md`, чтобы изменения не ломали running pipelines
- **Voice input в Telegram** — описание идеи голосом, обработка через Whisper
