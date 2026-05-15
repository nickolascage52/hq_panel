# PRD: AI Pipeline Module

**Проект:** AI Pipeline внутри AI Delivery HQ
**Версия:** 1.0
**Дата:** 2026-05-15
**Базируется на:** результаты аудита `docs/audit-2026-05-15.md`

---

## 1. Обзор

### 1.1 Что строим

Модуль автономной разработки клиентских проектов (`pipeline/`) внутри существующей операционной системы агентства (AI Delivery HQ). Модуль принимает на вход идею проекта (один промпт от владельца), автоматически формирует PRD, разбивает на спринты, запускает мультиагентную команду Claude Code, валидирует результат и доводит проект до состояния «готов к финальному review».

### 1.2 Зачем

Текущая AI Команда (23 prompt-агента) — **text-only**: генерирует текст, но не пишет код, не работает с файлами, не делает коммитов. Она была спроектирована до того, как стал доступен Claude Code SDK с tool use, файловыми операциями и git-интеграцией.

Цель нового модуля — **сократить операционное время владельца** на каждый клиентский проект (лендинг, бот, AI-ассистент, n8n-автоматизация и т.д.) с дней до часов, выполняя 80%+ работы автономно.

### 1.3 Чего НЕ строим

- **Не строим систему «один промпт → задеплоенный продакшен без человека».** Это не достижимо при текущем уровне моделей. Финальный review всегда за человеком.
- **Не строим автогенератор уникального визуального дизайна.** Pipeline даёт «дефолтно-аккуратно» по стандартам агентства. Уникальный дизайн — отдельный flow.
- **Не строим замену людям-исполнителям полностью.** Сложные интеграции, кастомная бизнес-логика, нюансы общения с клиентом — остаются за людьми.
- **Не переписываем существующий HQ с нуля.** Pipeline — новый модуль `pipeline/`, навешиваемый рядом с `agents/`.

---

## 2. Целевой пользователь

Владелец агентства (Никита Морус) и в будущем — PM-роль. Сценарии работы:

- В HQ-панели создаёт новый pipeline-проект, вводит идею клиента или внутреннюю задачу.
- Опционально подтверждает PRD и план спринтов, если уровень автономии < 3.
- Получает уведомления в Telegram о ключевых событиях.
- Открывает HQ-панель → новый раздел «AI Pipeline» → видит прогресс проекта.
- В конце получает готовый к review результат: git-репо с веткой, preview URL, отчёт.

---

## 3. Core user flow

### 3.1 Создание нового pipeline-проекта

1. Владелец заходит в HQ → раздел **AI Pipeline** → кнопка **«Новый проект»**.
2. Заполняет форму:
   - Описание идеи (textarea, обязательно)
   - Тип проекта (dropdown: landing, telegram_bot, n8n, ai_assistant, custom)
   - Уровень автономии (1/2/3)
   - Стратегия деплоя (none/vercel/aeza-subdomain/custom)
   - Привязка к существующему `delivery_project` (опц., через FK) или создание нового
3. Нажимает «Запустить».
4. Pipeline стартует на бэкенде:
   - Создаётся запись в `delivery_projects` (или используется существующая)
   - Создаётся запись в новой таблице `pipeline_runs`
   - Запускается фоновая задача (asyncio.create_task)
   - WebSocket `/ws/pipeline/{run_id}` стримит прогресс

### 3.2 Жизненный цикл pipeline-проекта (фазы)

```
Phase 1: Prompt refinement
  └─ /prompt-forge skill задаёт уточняющие вопросы (если идея сырая)
  └─ Готовый "production prompt" → docs/prompt.md

Phase 2: PRD generation
  └─ prd-builder agent → docs/PRD.md

Phase 3: Architecture decision
  └─ architecture-decider agent читает agency/standards/<type>.md
  └─ → docs/ARCHITECTURE.md + CLAUDE.md проекта

Phase 4: Sprint planning
  └─ sprint-planner agent → docs/sprints/sprint-N-*.md

[если autonomy_level < 3 — пауза на approval]

Phase 5: Sprint execution (loop по каждому спринту)
  ├─ Spawn agent team в tmux session
  │   ├─ architect (Opus): фиксирует контракт
  │   ├─ builder-frontend/backend (Sonnet): исполняют задачи
  │   └─ validator (Haiku): тесты, типы, билд после каждой задачи
  ├─ Waits for completion or rate-limit pause
  ├─ Post-sprint validation:
  │   ├─ code-reviewer subagent
  │   ├─ prd-compliance-checker subagent
  │   └─ e2e-tester (если применимо)
  ├─ Commit + push в git
  └─ Telegram: "✅ Sprint N done"

Phase 6: Final validation
  ├─ Full build/test/lint pass
  ├─ Deploy на preview-окружение
  └─ PRD compliance check на весь проект

Phase 7: Handoff
  └─ Telegram + HQ: "🎉 Проект готов к финальному review"
  └─ Статус delivery_project: "На проверке"
```

### 3.3 Управление в процессе

Владелец может в любой момент:
- **Pause** — приостановить pipeline вручную
- **Resume** — возобновить
- **Abort** — отменить (создаётся бэкап-ветка)
- **Send directive** — послать дополнительную инструкцию активной сессии (через чат в HQ или Telegram)

---

## 4. Функциональные требования

### 4.1 Pipeline lifecycle management

| FR | Описание |
|----|----------|
| FR-1.1 | Создание pipeline-run через `POST /api/pipeline/runs` с обязательными полями: `idea`, `project_type`, `autonomy_level`, `deploy_strategy` |
| FR-1.2 | Чтение состояния pipeline-run через `GET /api/pipeline/runs/{id}` |
| FR-1.3 | Список pipeline-runs с фильтрами через `GET /api/pipeline/runs` |
| FR-1.4 | Управление состоянием: `POST /api/pipeline/runs/{id}/{pause|resume|abort}` |
| FR-1.5 | Отправка директивы в активную сессию: `POST /api/pipeline/runs/{id}/directive` |

### 4.2 Phase execution

| FR | Описание |
|----|----------|
| FR-2.1 | Каждая фаза имеет state machine с состояниями: `pending`, `in_progress`, `awaiting_approval`, `done`, `failed` |
| FR-2.2 | Phase 4 (Sprint planning) при `autonomy_level < 3` останавливается и ждёт approval через `POST /api/pipeline/runs/{id}/approve` |
| FR-2.3 | Phase 5 (Sprint execution) выполняется по одному спринту за раз последовательно |
| FR-2.4 | При неудаче фазы — pipeline переходит в `failed`, владелец получает уведомление |

### 4.3 Agent team management

| FR | Описание |
|----|----------|
| FR-3.1 | Каждый pipeline-run работает в изолированной tmux-сессии на сервере |
| FR-3.2 | Состав команды зависит от типа спринта (frontend-only, backend-only, full-stack) |
| FR-3.3 | Сессия фиксируется в `pipeline_runs.tmux_session_name` |
| FR-3.4 | Каждый агент работает в своём git worktree (для параллельных задач) |

### 4.4 Rate limit handling

| FR | Описание |
|----|----------|
| FR-4.1 | Перед запуском фазы — проверка `pipeline_rate_limits` (текущее потребление Opus/Sonnet/Haiku) |
| FR-4.2 | При >70% weekly Opus — даунгрейд builders на Sonnet |
| FR-4.3 | При >70% weekly Sonnet — даунгрейд validators на Haiku |
| FR-4.4 | При >90% всех моделей — пауза pipeline, уведомление в Telegram с эстимейтом resume time |
| FR-4.5 | Автоматический resume по истечении окна лимита (queue runner проверяет каждые 30 сек) |

### 4.5 Communication & monitoring

| FR | Описание |
|----|----------|
| FR-5.1 | WebSocket `/ws/pipeline/{run_id}` — стриминг событий: phase changes, task completion, commits, errors |
| FR-5.2 | События также пишутся в `pipeline_events` таблицу для истории |
| FR-5.3 | Telegram-уведомления о ключевых событиях (старт, конец фазы, нужен approval, упёрся в лимит, готов к review) |
| FR-5.4 | Чат с pipeline в контексте проекта: `POST /api/pipeline/runs/{id}/chat` — пишешь, AI отвечает в контексте состояния проекта |

### 4.6 Integration с существующими сущностями

| FR | Описание |
|----|----------|
| FR-6.1 | Pipeline-run опционально привязан к `delivery_projects.id` через FK |
| FR-6.2 | Каждая фаза создаёт `delivery_stages` запись, каждая задача спринта — `delivery_tasks` |
| FR-6.3 | Поля `delivery_tasks.branch_name`, `pull_request_url`, `preview_url`, `production_url` заполняются автоматически |
| FR-6.4 | Pipeline-агенты регистрируются как `executors` с `level='ai_pipeline_worker'` |
| FR-6.5 | Каждый AI-вызов логируется в существующую таблицу `agent_executions` |

---

## 5. Non-functional requirements

### 5.1 Performance

- Pipeline-run для типового лендинга должен пройти все фазы за ≤ 8 часов реального времени (включая ожидание rate limits).
- API endpoints должны отвечать < 200ms (95p) для read-операций.
- WebSocket события должны доставляться < 1сек после события.

### 5.2 Reliability

- Pipeline должен выживать рестарт сервиса (состояние в БД, не в памяти).
- Сессии в HQ должны выживать рестарт (миграция с in-memory на DB — Sprint 1).
- При сбое одной фазы — pipeline останавливается, не теряет работу, ждёт ручного решения.
- Все коммиты должны быть atomic (один task = один коммит с понятным сообщением).

### 5.3 Security

- Все секреты в `.env`, никогда в коде (Sprint 1 ротация ключей).
- pipeline-агенты работают в изолированной директории, не имеют доступа к продакшен-БД.
- Только владелец (`role='owner'`) может запускать/останавливать pipeline.
- Каждое действие логируется в `pipeline_events` для аудита.

### 5.4 Mobile

- HQ-панель раздела «AI Pipeline» должна работать на mobile (bottom sheets, FAB).
- Telegram-канал — основной канал контроля с телефона.

### 5.5 Compatibility

- Совместимость со стеком: FastAPI 0.110, SQLite (aiosqlite), Python 3.13, ванильный JS.
- Совместимость со старой AI Командой — параллельная работа, без удаления до Sprint 5.

---

## 6. Domain glossary

| Термин | Определение |
|--------|-------------|
| **Pipeline run** | Один экземпляр автономной разработки проекта от идеи до handoff. Соответствует записи в `pipeline_runs`. |
| **Phase** | Этап жизненного цикла pipeline (Phase 1-7). |
| **Sprint** | Один из спринтов Phase 5, содержит атомарные задачи. |
| **Agent team** | Группа Claude Code субагентов в одной tmux-сессии, выполняющая один спринт. |
| **Autonomy level** | 1 = подтверждаешь архитектуру и переходы между спринтами; 2 = подтверждаешь только PRD и план; 3 = только начальный промпт. |
| **Deploy strategy** | none / vercel / aeza-subdomain / custom — куда деплоить результат. |
| **Directive** | Сообщение от владельца в активную pipeline-сессию (через HQ или Telegram). |
| **Rate budget** | Текущий остаток лимитов Claude Max на Opus/Sonnet/Haiku. |

---

## 7. Brand & voice

UI новой страницы должен соответствовать существующей дизайн-системе HQ:
- Тёмная тема по умолчанию (CSS-переменные из `_base.css`)
- Палитра: фиолетовый `#7c3aed → #a855f7` (как в HQ PRD v1.0)
- Inter font, Lucide icons
- 8/12/14px border radius
- Mobile bottom sheets

Telegram-сообщения — короткие, структурированные, с эмодзи-маркерами (✅⚠️❌🤔⏰🔔).

---

## 8. Success criteria (Definition of Done для всего проекта)

Проект считается успешно завершённым когда:

1. **Все 5 спринтов закрыты** (см. `docs/sprints/_index.md`)
2. **Git в проекте работает**, история чистая, `.gitignore` правильный
3. **Все ключи отозваны и переустановлены**, `.env.example` — только плейсхолдеры
4. **`hq_sessions` в БД**, рестарт сервиса не разлогинивает
5. **Pipeline-модуль работает**: можно создать pipeline-run через HQ, отследить прогресс в UI и Telegram, получить рабочий результат для тестового проекта типа `landing`
6. **Первый реальный pipeline-run выполнен**: создан тестовый landing-проект через систему, доведён до handoff, владелец может принять результат
7. **Старая AI Команда** остаётся жива и работоспособна (Telegram-бот не сломан)
8. **Документация обновлена**: `ai_agency/CLAUDE.md` дополнен разделом про pipeline, README актуален
9. **E2E тесты** покрывают основной flow создания pipeline-run

---

## 9. Constraints & risks

### 9.1 Technical constraints

- **SQLite + параллельность**: при множественных pipeline-runs одновременно — риск `database is locked`. Решение в ARCHITECTURE: WAL mode + sequential processing с очередью.
- **Claude Max лимиты**: один полноценный pipeline-run может съесть 30-70% недельного лимита Opus. Реальные ожидания: 1-2 активных pipeline в неделю.
- **Telegram-бот зависит от старого orchestrator**: нельзя удалить `agents/` до Sprint 5.
- **Анализ `anthropic>=0.40.0,<1` vs `claude-agent-sdk`**: возможны конфликты зависимостей. Проверить в Sprint 2.

### 9.2 Operational constraints

- Деплой на текущий сервер `89.22.235.144` без CI/CD. Все деплои через WinSCP + `systemctl restart`.
- Один владелец — никакой команды разработчиков нет. Все спринты выполняются Claude Code под наблюдением владельца.

### 9.3 Out-of-scope для v1.0

- Параллельная разработка нескольких pipeline-runs (v1: один за раз, очередь хранится в БД)
- Multi-tenancy (отдельные клиенты с своими настройками)
- Кастомные agent personas (v1: фиксированный набор)
- Биллинг клиентов за использование pipeline
- Поддержка проектов, требующих доступа к private services (Stripe, custom OAuth и т.д.) — v1 работает только со стандартными агентскими стеками

### 9.4 Risks

| Риск | Митигация |
|------|-----------|
| Pipeline галлюцинирует и пишет нерабочий код | code-reviewer + validator + prd-compliance-checker на каждом спринте |
| Rate limit upgrade слишком агрессивный, валим качество | Sprint 4 — fine-tune downgrade thresholds на основе первых прогонов |
| SQLite блокируется при параллельных pipeline-runs | v1: ограничение «1 активный pipeline-run одновременно», очередь в БД |
| Telegram-бот ломается при рефакторинге | Sprint 1-4 не трогают `agents/` и `telegram_bot.py`. Sprint 5 — точечный рефакторинг с тестами |
| Утечка секретов в репо после git init | Sprint 1 явная задача: `.gitignore` + проверка `.env*` в нём + audit `git status` перед первым коммитом |

---

## 10. Open questions (на момент создания PRD)

Эти вопросы решаются по ходу:

1. **Где хранить pipeline-workspace на сервере?** Предложение: `/var/www/ai_agency/pipeline_workspaces/<run_id>/`. Изоляция git worktree на проект.
2. **Деплой preview-окружения** — на отдельный поддомен `preview-<run_id>.hq.ai-delivery.shop` или Vercel? Решение в Sprint 4.
3. **GitHub repos**: создавать новый repo на каждый pipeline-run или использовать один monorepo? Предложение: новый repo на каждый клиентский проект, привязка через `delivery_projects.github_repo_url`.
4. **`delivery.html` сломан?** (из аудита). Проверить в Sprint 1, починить если да.
5. **Shell-агенты в `01_AGENTS/` и `scripts/01..12_*.sh`** — что с ними? Предложение: deprecate в Sprint 5, оставить как референс.

---

## Приложение: что переиспользуем из существующего HQ

Из аудита, секция 8.2 — критически важно для архитектора. Из существующих таблиц используем:

- `delivery_projects` — как backbone pipeline-run
- `delivery_stages` — как фазы
- `delivery_tasks` — атомарные задачи (поля `branch_name`, `pull_request_url`, `preview_url`, `production_url` буквально под нас)
- `delivery_checklist`, `delivery_comments` — переиспользуем как есть
- `delivery_templates` — расширяем под pipeline templates
- `executors` — регистрируем agent personas с уровнем `ai_pipeline_worker`
- `agent_executions` — лог каждого Claude вызова
- `knowledge_base` — контекст проекта (PRD клиента, brief, etc)
- `hq_users.github_username` — связь с GitHub
- WebSocket `/ws/task/{id}` — паттерн стриминга
- `agency_context_loader` — паттерн с приоритетами и кэшем

Новые таблицы добавляются **только там где существующие действительно не подходят** (см. ARCHITECTURE).
