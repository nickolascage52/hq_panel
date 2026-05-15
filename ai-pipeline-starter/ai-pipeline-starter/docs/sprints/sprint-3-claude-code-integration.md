# Sprint 3: Claude Code Integration (Phases 1-4)

**Цель:** научить pipeline реально запускать Claude Code через SDK. После этого спринта pipeline проходит фазы 1-4 (от идеи до плана спринтов) для тестовой идеи и формирует полную проектную документацию.

**Длительность:** 4-5 дней по 2-3 часа.

**Зависимости:** Sprint 2 завершён.

---

## Задачи

### T-3-001: Реализовать claude_runner.py

**Type:** feature
**Files:** `ai_agency/pipeline/claude_runner.py`
**Acceptance:**
- Класс `ClaudeRunner`
- Метод `async run_agent(workspace_path, agent_persona, prompt, model, timeout) -> AsyncIterator[Event]`
- Использует `claude-agent-sdk`:
  ```python
  from claude_agent_sdk import ClaudeAgent, ClaudeCodeOptions

  options = ClaudeCodeOptions(
      cwd=workspace_path,
      model=f'claude-{model}-4-7-latest' if model == 'opus' else f'claude-{model}-4-6-latest',
      agents=[agent_persona],
      max_turns=50,
  )
  async with ClaudeAgent(options=options) as agent:
      async for event in agent.query(prompt):
          yield event
  ```
- Обработка ошибок: rate limit, network, timeout
- Логирование каждого вызова в `agent_executions` таблицу
- Закоммитить

**Estimate:** L (90 минут)
**Depends-on:** Sprint 2 завершён

---

### T-3-002: Реализовать git_manager.py

**Type:** feature
**Files:** `ai_agency/pipeline/git_manager.py`
**Acceptance:**
- Класс `GitManager(workspace_path)`
- Методы:
  - `init_repo()` — `git init`, базовый коммит
  - `create_branch(name)` — `git checkout -b`
  - `commit_all(message)` — `git add . && git commit -m`
  - `push(remote, branch)` — `git push`
  - `create_worktree(branch_name, path)` — для параллельной работы builders
  - `merge_worktrees(target_branch, source_branches)` — объединение работы
  - `get_status()` — `git status --porcelain`
  - `get_diff(against='main')` — для code review
- Использует GitPython или subprocess (выбор обоснован в docs/dependency-decisions.md)
- Закоммитить

**Estimate:** L (90 минут)
**Depends-on:** Sprint 2

---

### T-3-003: Реализовать tmux_manager.py

**Type:** feature
**Files:** `ai_agency/pipeline/tmux_manager.py`
**Acceptance:**
- Класс `TmuxManager(session_name)`
- Методы:
  - `create()` — `tmux new -d -s <name>`
  - `exists()` — `tmux has-session -t <name>`
  - `send_keys(text, enter=True)` — `tmux send-keys -t <name> ...`
  - `capture_pane()` — содержимое сессии для логов
  - `kill()` — `tmux kill-session -t <name>`
- Использует `asyncio.subprocess`
- Закоммитить

**Estimate:** M (60 минут)
**Depends-on:** Sprint 2

---

### T-3-004: Создать agency/standards/landing.md

**Type:** content
**Files:** `agency/standards/landing.md`
**Acceptance:**
- Документ описывает стандарт агентства для лендингов:
  - Stack: Next.js 15 (app router), TypeScript, Tailwind CSS 4, shadcn/ui, react-hook-form + zod, framer-motion, lucide-react
  - Folder structure (см. шаблон из ARCHITECTURE.md)
  - Conventions (server components by default, no inline styles, etc.)
  - Performance budget (LCP < 2.5s mobile)
  - Что не использовать (jQuery, Material UI, styled-components)
  - Telegram CTA pattern (utility в /lib/telegram.ts)
- Документ переносится из nesting starter pack
- Закоммитить

**Estimate:** M (45 минут)
**Depends-on:** —

---

### T-3-005: Реализовать Phase 1 — Prompt refinement

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase1_prompt.py`
**Acceptance:**
- Phase 1 проверяет raw_idea:
  - Если идея уже подробная (>500 символов и содержит конкретику) — используется как production_prompt без изменений
  - Если идея краткая — запускает Claude через `claude_runner` с инструкцией скила `/prompt-forge`
- Скил `/prompt-forge` уже есть у пользователя в `~/.claude/skills/prompt-forge/`
- Результат сохраняется в `pipeline_runs.production_prompt` и в `<workspace>/docs/prompt.md`
- Событие `phase_completed` в `pipeline_events`
- E2E:
  - Создать run с короткой raw_idea
  - Дождаться Phase 1
  - В pipeline_runs.production_prompt должно быть детальное ТЗ

**Estimate:** L (90 минут)
**Depends-on:** T-3-001

---

### T-3-006: Создать скил /prd-builder

**Type:** feature
**Files:** `~/.claude/skills/prd-builder/SKILL.md`
**Acceptance:**
- Скил создаётся в директории пользователя (один раз, переиспользуется)
- Содержимое — см. PRD раздел 2.2
- После создания скила — Phase 2 сможет его вызвать

**Estimate:** M (45 минут)
**Depends-on:** —

---

### T-3-007: Реализовать Phase 2 — PRD generation

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase2_prd.py`
**Acceptance:**
- Phase 2 запускает Claude в workspace с задачей:
  ```
  Read /docs/prompt.md. Use /prd-builder skill to generate /docs/PRD.md.
  Reference /agency/standards/<project_type>.md if exists.
  ```
- После завершения — проверка что `<workspace>/docs/PRD.md` существует и не пустой
- Событие `phase_completed`
- Если файла нет или пустой — `PhaseExecutionError`

**Estimate:** M (60 минут)
**Depends-on:** T-3-005, T-3-006

---

### T-3-008: Создать скил /architecture-decider

**Type:** feature
**Files:** `~/.claude/skills/architecture-decider/SKILL.md`
**Acceptance:**
- Содержимое — см. PRD раздел 2.3
- Скил читает PRD + agency/standards/<type>.md → производит ARCHITECTURE.md и CLAUDE.md

**Estimate:** M (30 минут)
**Depends-on:** —

---

### T-3-009: Реализовать Phase 3 — Architecture decision

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase3_architecture.py`
**Acceptance:**
- Phase 3 запускает Claude с задачей:
  ```
  Read /docs/PRD.md and /agency/standards/<project_type>.md.
  Use /architecture-decider skill to generate /docs/ARCHITECTURE.md and /CLAUDE.md.
  ```
- После — проверка существования файлов
- Если `autonomy_level < 3` — после Phase 3 pipeline ставится в `awaiting_approval`
- Telegram-уведомление: «🔔 Architecture готова, нужно ваше одобрение»

**Estimate:** M (60 минут)
**Depends-on:** T-3-007, T-3-008

---

### T-3-010: Создать скил /sprint-planner

**Type:** feature
**Files:** `~/.claude/skills/sprint-planner/SKILL.md`
**Acceptance:**
- Содержимое — см. PRD раздел 2.4
- Скил режет PRD на спринты, каждый спринт — на задачи

**Estimate:** M (30 минут)
**Depends-on:** —

---

### T-3-011: Реализовать Phase 4 — Sprint planning

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase4_sprints.py`
**Acceptance:**
- Phase 4 запускает Claude с задачей создать sprints
- Для каждого созданного `sprint-N-*.md` файла создаётся запись в `pipeline_sprints`
- Также создаётся зеркальная запись в `delivery_stages` (чтобы видно было в HQ)
- Если `autonomy_level < 2` — пауза на approval

**Estimate:** L (90 минут)
**Depends-on:** T-3-009, T-3-010

---

### T-3-012: Approval endpoints

**Type:** feature
**Files:** `ai_agency/pipeline_api.py`
**Acceptance:**
- `POST /api/pipeline/runs/{id}/approve` — продолжает с awaiting_approval статуса
- Сохраняет approval событие в pipeline_events
- Возобновляет PipelineRunner.resume()
- E2E:
  - Запустить run с autonomy_level=2
  - Pipeline останавливается после Phase 4
  - `POST /approve` → продолжает к Phase 5

**Estimate:** M (45 минут)
**Depends-on:** T-3-011

---

### T-3-013: E2E test для Phase 1-4

**Type:** test
**Files:** `ai_agency/tests/test_pipeline_phases_1_4.py`
**Acceptance:**
- Тест:
  1. Создать pipeline-run с raw_idea = "Простой одностраничный лендинг для AI-агентства Никиты Моруса с CTA на Telegram"
  2. Запустить pipeline (autonomy_level=3 чтобы не нужны approvals)
  3. Подождать завершения Phase 1-4 (может быть 10-20 минут)
  4. Проверить:
     - `<workspace>/docs/prompt.md` существует
     - `<workspace>/docs/PRD.md` существует и >2KB
     - `<workspace>/docs/ARCHITECTURE.md` существует
     - `<workspace>/CLAUDE.md` существует
     - `<workspace>/docs/sprints/` содержит ≥3 файла
     - В `pipeline_sprints` ≥3 записи
- Это первый «реальный» тест который тратит токены Max

**Estimate:** L (60-90 минут, плюс ~10-20 мин выполнения)
**Depends-on:** T-3-012

---

## Definition of done for sprint 3

- [ ] Все задачи T-3-001..T-3-013 выполнены
- [ ] `claude_runner.py`, `git_manager.py`, `tmux_manager.py` работают
- [ ] Скилы `/prd-builder`, `/architecture-decider`, `/sprint-planner` созданы
- [ ] `agency/standards/landing.md` создан
- [ ] Phases 1-4 работают, создают реальные документы
- [ ] Approval endpoints работают
- [ ] E2E test проходит

## Acceptance demo

После Sprint 3 ты должен мочь:

1. Через API создать pipeline-run с короткой идеей
2. Подождать 15-20 минут
3. Зайти в `pipeline_workspaces/<run_id>/` и увидеть:
   - `docs/prompt.md` — обработанный prompt
   - `docs/PRD.md` — полный PRD
   - `docs/ARCHITECTURE.md` — архитектура
   - `CLAUDE.md` — правила для будущих агентов
   - `docs/sprints/` — 3-7 спринт-файлов
4. В HQ (через delivery view, который через delivery_stages) — видны все спринты как stages

Это уже **по-настоящему ценная** функциональность — pipeline превращает идею в полную проектную документацию.

## Что НЕ делаем в Sprint 3

- НЕ выполняем реальные спринты (это Sprint 4, Phase 5)
- НЕ деплоим (это Sprint 4, Phase 7)
- НЕ строим UI (это Sprint 4)
- НЕ trогaем старую AI Команду

## Известные риски

- **Лимиты:** один полный прогон Phase 1-4 может съесть 5-15% недельного Opus. Не запускай тестовые runs без необходимости.
- **Скилы могут вести себя нестабильно:** если Claude в фазе ошибётся или не сохранит файл — Phase сфейлится. В таких случаях:
  1. Прочитать `pipeline_events` для этого run
  2. Прочитать что Claude реально сделал в workspace
  3. Подкрутить скил или промпт фазы
  4. Перезапустить run (или resume с failed phase)
- **claude-agent-sdk events:** API может отличаться от моих предположений в коде. Если будут errors — читать актуальную документацию SDK.
