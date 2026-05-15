# Sprint 4 — Final Report

**Дата:** 2026-05-15
**Ветка:** `main` на `NickolasCage52/HQ_Panel`
**Локальная часть:** ✅ ЗАВЕРШЕНА (12/12 задач)
**Live E2E:** ⏸ Skipped — требует ANTHROPIC_API_KEY (отозван в T-1-006)

---

## Что сделано

| ID | Задача | Что | Статус |
|---|---|---|---|
| T-4-001 | RateLimitManager | get_state/select_model_for_task/should_pause/get_resume_estimate/record_usage + DOWNGRADE_CHAINS per task type | ✅ |
| T-4-002 | Phase 5 Execution | Iterates pipeline_sprints, marks active->done, emits sprint_started/completed events, checks rate_limit before start | ✅ stub (real spawn — v1.1) |
| T-4-003 | Phase 6 Validation | Inspects workspace для package.json/pyproject.toml + emits validation_inspection event | ✅ stub (real build — v1.1) |
| T-4-004 | Phase 7 Handoff | Writes docs/final-report.md, runs deploy(strategy), updates delivery_projects.status='На проверке', emits handoff_complete | ✅ |
| T-4-005 | deploy.py | 4 strategies: none (no-op), vercel/aeza/custom (stubs) | ✅ |
| T-4-006 | pipeline.html | List view с metric cards, filter, grid карточек, modal create. Mobile responsive. | ✅ |
| T-4-007 | pipeline-run-detail.html | Header с status/progress/phase pills + 4 tabs (Overview/Documents/Sprints/Events) + WebSocket live updates + Approve button | ✅ |
| T-4-008 | hq-pipeline.js | HQPipeline namespace: listRuns/createRun/getRun/getEvents/approveRun + connectWebSocket + helpers | ✅ |
| T-4-009 | Sidebar update | _components.js: добавлен 'AI Pipeline' (icon: cpu, owner-only). 'AI Команда' переименована в 'AI Команда (legacy)' | ✅ |
| T-4-010 | Telegram notifier | pipeline/telegram_notifier.py — отдельный watcher, НЕ трогает telegram_bot.py. main.py запускает background task. Notify on: run_started/approval_needed/paused/handoff_complete/run_failed | ✅ |
| T-4-011 | Mobile adaptation | Inline media queries в pipeline.html и pipeline-run-detail.html (single-column grid, vertical modal actions, сжатые tabs <768px) | ✅ |
| T-4-012 | E2E test | tests/test_pipeline_e2e.py — full pipeline (60-120 min), `@pytest.mark.skipif(not _api_key_real())` — auto-skip без живого ключа | ✅ (skipped runtime) |

## Sprint 4 commits

```
0b1edc1 [T-4-006..009+011] feat(ui): pipeline.html + run-detail + hq-pipeline.js + sidebar
db48681 [T-4-001..005] feat(pipeline): rate_limit + deploy + Phase 5/6/7 (Sprint 4 backend)
```
(+ T-4-010 + T-4-012 + final report — следующий коммит)

## Definition of Done

- ✅ Все T-4-001..T-4-012 в коммитах
- ✅ Phases 5-7 работают (stub mode для v1.0; real spawn в v1.1 backlog когда API key вернётся)
- ✅ Rate limit handling logic + DOWNGRADE_CHAINS реализованы
- ✅ HQ UI: pipeline.html (list/create) + pipeline-run-detail.html (detail с 4 tabs + WS live)
- ✅ WebSocket live updates на UI (event prepend + auto-refresh header)
- ✅ Telegram уведомления — реальная реализация без касания telegram_bot.py (отдельный watcher)
- ✅ Mobile adaptation — media queries в обоих новых HTML
- ⏸ Full E2E test существует, но **skipped** до ANTHROPIC_API_KEY restore
- ✅ Регрессий: pytest test_pipeline_skeleton.py — 4 passed in 39.49s

## Critical decisions

### 1. Phase 5/6 — stubs vs real

Phase 5 (sprint execution) и Phase 6 (validation) **в v1.0 stubs** — реальная работа требует:
- (5) ANTHROPIC_API_KEY + tmux + git worktrees + per-sprint architect/builder/validator spawn
- (6) Subprocess `npm run build` / `pytest` + результат feedback в pipeline_events

В Sprint 4 добавлено ВСЁ orchestration scaffolding (per-sprint loop, status transitions, events emission, rate-limit check), но реальный Claude spawn вынесен в **v1.1 backlog**. Это значит при PIPELINE_FORCE_STUB=true тест проходит зеленым; при реальном API key Phase 5 успеет emit sprint_started/completed но не будет писать код проекта.

### 2. Telegram notifier как отдельный модуль

План T-4-010 предлагал минимальные правки в `telegram_bot.py`. Я выбрал **отдельный модуль** `pipeline/telegram_notifier.py` потому что:
- `telegram_bot.py` помечен как untouchable до Sprint 5 (CLAUDE.md проекта)
- Изоляция: pipeline-уведомления могут эволюционировать без касания старого бота
- main.py запускает watcher через `asyncio.create_task` — те же гарантии "не блокирует событийный цикл"

Бот всё ещё handle'ит свои команды (/report, /clients, etc), а pipeline notifications приходят как обычные сообщения от того же бота-аккаунта.

### 3. UI без bundler/framework

`pipeline.html` (350 строк) и `pipeline-run-detail.html` (240 строк) — vanilla HTML+inline CSS+vanilla JS. Это согласуется с CLAUDE.md проекта (no React/Vue/Svelte). HQPipeline namespace — единственная shared зависимость.

Используется существующая дизайн-система через `_base.css` + `style.css` + CSS-переменные. Цвета status badges — palette из существующих карточек CRM.

WebSocket pattern: connect once, on close → fall back to 5s polling с `?since=lastEventId`. Это устойчиво к флапам сети.

### 4. Mobile-first inline

Mobile adaptation сделан inline в HTML (не отдельным файлом hq-mobile.css). Это **deliberate choice** для self-contained страниц — каждый pipeline page имеет свои specific breakpoints (single-column grid, vertical modal actions, сжатые tabs), и тащить их в общий hq-mobile.css было бы coupling.

### 5. Approve only via UI

Pipeline endpoint `POST /api/pipeline/runs/{id}/approve` (T-3-012) — единственный способ approval в v1.0. UI кнопка enabled только когда status='awaiting_approval'. Telegram-команда /approve — backlog v1.1 (требует tracking активного run-а в bot context).

## Что НЕ делали (по плану)

- ❌ Реальный spawn architect/builders/validator в Phase 5 (Claude API + tmux на Linux)
- ❌ Реальный `npm run build` / `pytest` в Phase 6 (нужно решить какие стеки support'им)
- ❌ Реальный Vercel/Aeza deploy (нужны токены, SSH ключи, nginx config)
- ❌ Pause/Resume/Abort UI кнопки (показаны как disabled с title='v1.1')
- ❌ Documents tab rendering (требует marked.js + workspace API)
- ❌ Sprints tab listing (нужен endpoint /api/pipeline/runs/{id}/sprints)
- ❌ Cost tracking per run
- ❌ Полноценный chat с pipeline

Все эти пункты в **backlog v1.1**.

## Acceptance demo (когда восстановят ANTHROPIC_API_KEY)

```
1. HQ → AI Pipeline → "+ Новый pipeline-run"
2. Заполнить форму (title, raw_idea, project_type=landing, autonomy=2, deploy=none)
3. Запустить
4. На pipeline-run-detail.html видно:
   - Header: status badge "Выполняется" (cyan)
   - Phase pills: prompt → prd → architecture (active)
   - Progress bar 0%, потом 14%, 28%, ...
   - Live events во вкладке Events: phase_started prompt, phase_completed prompt, ...
5. После Phase 4 — Telegram уведомление "🔔 Pipeline #1: нужно одобрение (sprints)"
6. В HQ нажать Approve
7. Pipeline продолжает (Phase 5/6/7 в v1.0 — быстрые stubs)
8. Финальное Telegram "🎉 Pipeline #1 готов к review"
9. delivery_projects (если был связан) теперь status='На проверке'
```

## Метрики

- **Файлов создано:** 6 (deploy.py, telegram_notifier.py, pipeline.html, pipeline-run-detail.html, hq-pipeline.js, test_pipeline_e2e.py)
- **Файлов модифицировано:** 6 (rate_limit.py, phase5/6/7, _components.js, main.py, test fixture, sprint-4-final-report.md)
- **Строк +/−:** ~+1500 / −60
- **Коммитов:** 4 (backend, UI, telegram+e2e, report)
- **Тесты:** 4 passed (test_pipeline_skeleton — без регрессий) + 1 skipped (full E2E)
- **Real Claude tokens used:** 0
- **Real Telegram messages sent:** 0 (TELEGRAM_OWNER_ID настроен, но pipeline runs запускались только в WEB_ONLY mode)
