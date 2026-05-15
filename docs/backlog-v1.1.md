# Backlog v1.1 — Что не вошло в v1.0

**Дата:** 2026-05-15
**Контекст:** AI Pipeline v1.0 (Sprint 1-5) закрывает каркас, основной flow и UI. Этот документ — что было сознательно отложено и почему.

---

## Critical (нужно для production-ready при возврате ANTHROPIC_API_KEY)

### CR-1. Phase 5 — реальный spawn архитектора+билдеров+валидатора

**Что:** Phase 5 в v1.0 — stub (per-sprint sleep + status update). Реальная реализация:
- Spawn architect (Opus) первым — фиксирует контракт типов
- Spawn builders (Sonnet) параллельно по git worktrees, по доменам (frontend/backend)
- Spawn validator (Haiku) после каждой задачи
- Spawn code-reviewer + prd-compliance-checker по окончанию sprint
- Merge worktrees → sprint branch → push

**Почему не v1.0:** требует real `ANTHROPIC_API_KEY` (отозван в Sprint 1 T-1-006), tmux на Linux (на Windows dev no-op), git worktrees на проектном workspace. Каркас orchestration в Sprint 4 готов, недостаёт самого spawn.

**Файлы:** `pipeline/phases/phase5_execution.py`, `pipeline/claude_runner.py` (расширить под per-task max_turns), `pipeline/git_manager.py` (используется как есть).

### CR-2. Phase 6 — реальный build/test/lint

**Что:** Phase 6 в v1.0 — только `validation_inspection` event. Реальная: subprocess `npm run build`, `pnpm test`, `pytest` (зависит от стека) + парсинг stderr + emit как pipeline_events.

**Почему не v1.0:** нужно решить какие стеки support'им сначала (по landing.md — Next.js 15), и как сообщать build errors обратно в pipeline runner.

### CR-3. Vercel deploy

**Что:** в v1.0 `deploy.py` для `'vercel'` — stub (требует `VERCEL_TOKEN` но ничего не запускает). Real: subprocess `vercel deploy --prod=false --token=...`, парсинг preview URL из stdout, сохранение в `pipeline_runs.github_repo_url` (rename → `production_url`).

### CR-4. Live `claude /usage` parsing для rate limit

**Что:** в v1.0 `RateLimitManager` хранит state в БД но **не обновляет** автоматически. Real: периодически (раз в N минут) парсить `claude /usage` CLI output → обновлять `pipeline_rate_limits.tokens_used_weekly`.

**Альтернатива:** ловить `RateLimitError` от SDK и инкрементально обновлять оценку (более грубо, но работает без CLI).

---

## High (полезно для UX, можно жить без)

### HI-1. Pause/Resume/Abort UI кнопки

В v1.0 в `pipeline-run-detail.html` они disabled с подсказкой `v1.1`. Backend endpoints (`/pause`, `/resume`, `/abort`) — нужно реализовать в `pipeline_api.py`. UI обвязка минимальная (HQPipeline namespace уже имеет stubs).

### HI-2. Documents tab rendering

В v1.0 показывает заглушку. Нужно: marked.js (CDN), endpoint `GET /api/pipeline/runs/{id}/files/{path}` для чтения workspace файлов, vanilla render PRD.md/ARCHITECTURE.md/sprint-N.md.

### HI-3. Sprints tab listing

Endpoint `GET /api/pipeline/runs/{id}/sprints` нужен. Render — kanban через SortableJS (уже используется в `project-detail.html`).

### HI-4. Pipeline chat в context проекта

`pipeline_chat_messages` таблица создана в Sprint 2. UI tab Chat в detail-странице нужен. Endpoints `GET/POST /api/pipeline/runs/{id}/chat`. Чат может посылать `directive` в активную Claude session (требует Phase 5 real spawn).

### HI-5. WebSocket reconnect с `?since=`

В v1.0 при close — fallback на 5s polling. Нужна нормальная логика reconnect c exponential backoff и `?since=lastEventId` чтобы не терять события.

### HI-6. Cost tracking per run

Сейчас `pipeline_rate_limits.tokens_used_weekly` глобальный (по модели). Per-run нужно: `tokens_per_run` колонка в `pipeline_runs` (или JOIN на `agent_executions.tokens_used`). UI: бейджик "$N.NN spent" на карточке run-а.

---

## Medium (приятно иметь)

### MD-1. Поддержка типов проектов: telegram_bot, n8n, ai_assistant

В v1.0 — только `landing` (есть `agency/standards/landing.md`). Нужны:
- `agency/standards/telegram_bot.md` (стек: aiogram 3.x + Python + SQLite)
- `agency/standards/n8n.md` (workflow JSON + custom nodes если нужно)
- `agency/standards/ai_assistant.md` (FastAPI + Anthropic SDK + RAG если нужно)

### MD-2. Параллельные pipeline-runs

В v1.0 `pipeline/queue.py` — stub. Очередь нужна когда несколько runs одновременно — иначе SQLite locks + token contention. Простая реализация: `pipeline_runs.status='pending'` ждёт пока активный (`running`/`paused_*`) не финиширует.

### MD-3. Voice input в Telegram через Whisper

Идея: пользователь в Telegram записывает голос с описанием идеи, бот через Whisper транскрибирует → создаёт pipeline-run. Нужно: Whisper API access, telegram bot voice handler, `POST /api/pipeline/runs` с готовым raw_idea.

### MD-4. GitHub OAuth для пользователей

В v1.0 push идёт от системного git config (`user.name="AI Pipeline"`, `user.email="pipeline@ai-delivery.local"`). Нужно: OAuth → каждый pipeline-run пушит от GitHub-аккаунта владельца. Связь через `hq_users.github_username`.

---

## Low (когда руки дойдут)

### LO-1. Multi-tenancy

Разделение клиентов по правам доступа к runs. Сейчас owner видит всё.

### LO-2. Кастомные agent personas через UI

В v1.0 — фиксированный набор persona в `~/.claude/agents/`. UI для редактирования — backlog.

### LO-3. Биллинг клиентов за use of pipeline

Когда будет cost tracking (HI-6) и понимание реальной цены — можно делать наценку и выставлять клиентам.

### LO-4. `delivery.html` clean-up after T-1-013 audit

Sprint 1 T-1-013 показал что `/api/delivery/*` endpoints существуют (false alarm). Но сама страница могла подкопить пыль за время Sprint 1-5. Smoke test (T-5-008) укажет что починить.

### LO-5. Удалить `static/admin/` (после v2.0)

Помечен `DEPRECATED.md` в T-5-004. После года в production — удалить.

### LO-6. Удалить shell-агенты в `01_AGENTS/` и `scripts/01..12_*.sh`

Помечены `DEPRECATED.md` в T-5-005. После того как Phase 5 real spawn заработает в v1.1 — переоценить, скорее всего удалим.

### LO-7. Self-healing на серьёзных ошибках

Сейчас если build упал 3+ раз — pipeline ставится на паузу. Можно добавить retry с разными моделями / разными промптами.

### LO-8. Обновить контекст в `agency/standards/` ежеквартально

Стек развивается (Next.js 15 → 16, Tailwind 4 → 5). Periodically check что `landing.md` etc актуальны.

---

## Принципы выбора что в v1.1

1. **Что нужно для real Claude calls** → CR-* (без них v1.0 формально работает но не делает code generation)
2. **Что улучшает UX без backend** → HI-1, HI-2, HI-3 (можно за 1-2 дня)
3. **Что расширяет use-cases** → MD-1 (новые типы проектов)
4. **Всё остальное** → когда будет время / запрос пользователей
