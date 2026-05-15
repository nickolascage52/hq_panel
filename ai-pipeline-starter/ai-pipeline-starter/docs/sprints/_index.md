# Sprints Index

5 спринтов, каждый = автономная единица работы. Можно остановиться после любого спринта.

## Sprint 1: Foundation (~2-3 дня)

**Цель:** закрыть критические инфра-блокеры из аудита перед началом разработки модуля.

- Git init + .gitignore + первый коммит + GitHub remote
- Ротация секретов (Anthropic API key, Telegram bot token)
- `.env.example` — только плейсхолдеры
- Миграция in-memory сессий → таблица `hq_sessions`
- Проверка/починка `delivery.html` и недостающих эндпоинтов
- Backup VPS перед началом работы над pipeline

**Завершение спринта:** проект в git, секреты ротированы, сессии переживают рестарт. Ничего нового функционально не добавляется.

**Файл:** `sprint-1-foundation.md`

---

## Sprint 2: Pipeline skeleton (~3-4 дня)

**Цель:** собрать каркас pipeline-модуля без интеграции с Claude Code SDK.

- Установить `claude-agent-sdk`, `GitPython` (проверить совместимость с `anthropic<1`)
- Создать `pipeline/` модуль с базовыми классами (PipelineRunner, Phase, Workspace)
- Создать БД-миграции для новых таблиц: `pipeline_runs`, `pipeline_sprints`, `pipeline_events`, `pipeline_chat_messages`, `pipeline_rate_limits`
- Создать `pipeline_api.py` с API-эндпоинтами (POST /api/pipeline/runs создаёт запись в БД, но не запускает execution)
- WebSocket `/ws/pipeline/{run_id}` (стримит события из `pipeline_events`)
- E2E-тест: создание run → запись в БД → событие в WebSocket

**Завершение спринта:** можно через API создавать pipeline-runs, видеть их в БД, получать события через WebSocket. Реального выполнения ещё нет — фаз пока stub-ы.

**Файл:** `sprint-2-pipeline-skeleton.md`

---

## Sprint 3: Claude Code integration (~4-5 дней)

**Цель:** научить pipeline реально запускать Claude Code и выполнять фазы.

- `claude_runner.py` — обёртка над `claude-agent-sdk`
- `tmux_manager.py` — управление tmux сессиями pipeline
- `git_manager.py` — init repo, worktree, commits
- Реализовать Phase 1 (Prompt refinement) — простейший, без UI
- Реализовать Phase 2 (PRD generation) — через скилл `/prd-builder`
- Реализовать Phase 3 (Architecture decision) — через скилл `/architecture-decider`
- Реализовать Phase 4 (Sprint planning) — через скилл `/sprint-planner`
- Создать `agency/standards/landing.md` (первый стандарт)
- E2E-тест на тестовой идее: «Сделай простой landing для X» → пройти фазы 1-4 → получить готовые `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/sprints/*.md` в workspace

**Завершение спринта:** для тестовой идеи pipeline проходит фазы 1-4 и формирует полную проектную документацию. Реальный код проекта ещё не пишет.

**Файл:** `sprint-3-claude-code-integration.md`

---

## Sprint 4: Full execution + HQ integration (~4-5 дней)

**Цель:** реализовать Phase 5-7 (исполнение спринтов, валидация, handoff) и интегрировать с HQ UI.

- Phase 5 — выполнение спринтов через Agent Team (architect + builders + validator)
- Phase 6 — финальная валидация (build, tests, lint, e2e)
- Phase 7 — handoff (final report, Telegram-уведомление, статус)
- Rate limit handling (downgrade на Sonnet/Haiku при лимитах Opus)
- HQ UI: `pipeline.html` (список и создание), `pipeline-run-detail.html` (детали)
- JS-модуль `hq-pipeline.js` с live-апдейтами
- Sidebar пункт «AI Pipeline» в `_components.js`
- Telegram-команды `/pipeline`, `/runs`, `/status`
- E2E-тест: создать pipeline-run для тестового landing через HQ → пройти все фазы → получить готовый код в workspace

**Завершение спринта:** работающий end-to-end pipeline для типа `landing`. Можно через HQ создать проект, видеть прогресс, получить готовый код.

**Файл:** `sprint-4-ui-and-hq-integration.md`

---

## Sprint 5: Cleanup, AI Команда deprecation (~2-3 дня)

**Цель:** убрать старую AI Команду или переключить её на новый модуль (там где это применимо), обновить документацию.

- Аудит того, что из старого `agents/` всё ещё активно используется (через grep + Telegram-бот)
- Перенести Telegram-бот команды `/agent`, `/report` на новый API (либо оставить старые если работают)
- Пометить `static/admin/` и `agents/team.html` (старую) как deprecated
- Решить судьбу shell-агентов в `01_AGENTS/` и `scripts/01..12_*.sh`
- Обновить `ai_agency/CLAUDE.md` с разделом про pipeline
- Обновить `OWNER_GUIDE.md`
- Создать demo-видео или markdown-инструкцию для повторного использования
- Smoke-test всех старых страниц HQ (убедиться что ничего не сломалось от изменений Sprint 1-4)

**Завершение спринта:** проект полностью переезжает на pipeline-модель. Старое — либо удалено, либо явно deprecated.

**Файл:** `sprint-5-cleanup-and-handoff.md`

---

## Когда стоит остановиться

После каждого спринта легитимная точка остановки:
- **После Sprint 1** — инфра готова, можно жить без pipeline ещё какое-то время.
- **После Sprint 2** — каркас есть, но без Claude Code интеграции пользы немного.
- **После Sprint 3** — pipeline умеет генерировать документы, но не код. Уже полезно для брифов.
- **После Sprint 4** — основная цель достигнута, pipeline работает.
- **После Sprint 5** — система чистая, нет легаси-долга.

## Riski между спринтами

| Sprint | Главный риск |
|--------|--------------|
| 1 | Сломать что-то в `database.py` при добавлении `hq_sessions` |
| 2 | Конфликт `claude-agent-sdk` с `anthropic<1` |
| 3 | claude-agent-sdk может не пробрасывать tools правильно в subagent (мы уже сталкивались с похожим) |
| 4 | Rate limit логика на практике может оказаться сложнее чем кажется |
| 5 | Telegram-бот ломается при попытке заменить старый orchestrator |
