# Sprint 4: Full Execution + HQ UI Integration

**Цель:** реализовать Phase 5-7 (исполнение спринтов, валидация, handoff) и интегрировать с HQ UI. После этого спринта работает end-to-end pipeline для типа `landing`.

**Длительность:** 4-5 дней по 2-3 часа.

**Зависимости:** Sprint 3 завершён.

---

## Задачи

### T-4-001: Реализовать rate_limit.py

**Type:** feature
**Files:** `ai_agency/pipeline/rate_limit.py`
**Acceptance:**
- Класс `RateLimitManager(db)`
- Методы:
  - `update_state()` — парсит `claude /usage` или ловит RateLimitError и обновляет `pipeline_rate_limits`
  - `select_model_for_task(task_type)` — возвращает 'opus' | 'sonnet' | 'haiku' | None
  - `should_pause()` — bool, true если все >90%
  - `get_resume_estimate()` — timestamp когда самый ранний reset
- Логика downgrade по PRD/ARCHITECTURE
- Закоммитить

**Estimate:** L (90 минут)
**Depends-on:** Sprint 3

---

### T-4-002: Реализовать Phase 5 — Sprint execution

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase5_execution.py`
**Acceptance:**
- Phase 5 итерирует по pipeline_sprints для run-а:
  - Для каждого sprint:
    - status='active'
    - Создать tmux session `pipeline-<run_id>-sprint-<n>`
    - Spawn architect agent (Opus) — фиксирует контракт
    - Spawn builder agents (Sonnet) — по worktrees, параллельно
    - Spawn validator (Haiku) — после каждой задачи
    - Merge worktrees → sprint branch
    - Run code-reviewer (Sonnet)
    - Run prd-compliance-checker (Opus)
    - Если ошибки и autonomy_level<3 — pause for approval
    - Commit + push
    - status='done'
- Каждый шаг — событие в pipeline_events
- На каждом шаге — check rate_limit, downgrade model если нужно

**Estimate:** XL (3+ часа)
**Depends-on:** T-4-001

**Заметки:**
- Это самая большая задача спринта. Можно разбить на подтаски:
  - T-4-002a: каркас цикла по спринтам
  - T-4-002b: spawn architect + builders
  - T-4-002c: post-sprint validation
  - T-4-002d: rate limit checks
- Тестировать на маленьком sprint (2-3 задачи).

---

### T-4-003: Реализовать Phase 6 — Final validation

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase6_validation.py`
**Acceptance:**
- Phase 6 запускает:
  - Финальный `pnpm build` / `npm run build` (зависит от стека)
  - Финальные тесты
  - Lint/typecheck
  - prd-compliance-checker на весь проект
- Если что-то падает — pause с детальным отчётом
- Если ок — переход к Phase 7

**Estimate:** L (90 минут)
**Depends-on:** T-4-002

---

### T-4-004: Реализовать Phase 7 — Handoff

**Type:** feature
**Files:** `ai_agency/pipeline/phases/phase7_handoff.py`
**Acceptance:**
- Phase 7:
  - Генерирует `<workspace>/docs/final-report.md` с summary
  - Деплоит на preview-окружение (если deploy_strategy != 'none')
  - Обновляет `delivery_projects.status` = 'На проверке' (review)
  - Telegram: «🎉 Pipeline #N готов к финальному review. Preview: <url>»
  - pipeline_runs.status = 'review'

**Estimate:** L (60-90 минут)
**Depends-on:** T-4-003

---

### T-4-005: Простой deploy strategy — Vercel или aeza-subdomain

**Type:** feature
**Files:** `ai_agency/pipeline/deploy.py`
**Acceptance:**
- Для `deploy_strategy='none'` — ничего не делаем, ставим production_url = NULL
- Для `deploy_strategy='vercel'`:
  - Проверить наличие `VERCEL_TOKEN` в .env
  - `vercel deploy --token=...` из workspace
  - Парсить вывод, сохранить URL в pipeline_runs/delivery_projects
- Для `deploy_strategy='aeza'`:
  - Скопировать build на сервер в `/var/www/preview/<run_id>/`
  - Создать nginx config (опц.) или использовать общий preview-домен
  - URL: `https://preview-<run_id>.hq.ai-delivery.shop`

**Estimate:** L (90-120 минут)
**Depends-on:** T-4-004

**Заметки:**
- Для MVP достаточно одной стратегии (например vercel). Остальные — в backlog v1.1.

---

### T-4-006: Создать pipeline.html

**Type:** ui
**Files:** `ai_agency/static/hq/pipeline.html`
**Acceptance:**
- Структура страницы как у delivery.html:
  - Топбар с заголовком «AI Pipeline»
  - Метрики (active, awaiting_approval, in_review, done за месяц)
  - Кнопка «Новый pipeline-run» → открывает модальное окно
  - Grid карточек pipeline-runs
- Стили — из существующих `_base.css`, `style.css`
- Использует `_components.js` для sidebar и auth
- Модалка создания:
  - title, raw_idea (textarea)
  - project_type (select)
  - autonomy_level (radio)
  - deploy_strategy (select)
  - кнопка «Запустить»

**Estimate:** L (120 минут)
**Depends-on:** T-4-005

---

### T-4-007: Создать pipeline-run-detail.html

**Type:** ui
**Files:** `ai_agency/static/hq/pipeline-run-detail.html`
**Acceptance:**
- URL: `/hq/pipeline-run-detail.html?id=<run_id>`
- Header: статус, прогресс bar, кнопки управления (Pause/Resume/Abort)
- Вкладки:
  - **Overview** — текущая фаза, последние события, links
  - **PRD/Architecture** — рендер markdown (через `marked.js` через CDN)
  - **Sprints** — kanban с задачами
  - **Chat** — пока stub (полноценный чат — v1.1)
  - **Events** — полная лента
- WebSocket connect к `/ws/pipeline/<id>` для live updates
- Отображение rate-limit status в углу

**Estimate:** XL (3 часа)
**Depends-on:** T-4-006

---

### T-4-008: Создать hq-pipeline.js

**Type:** ui
**Files:** `ai_agency/static/hq/hq-pipeline.js`
**Acceptance:**
- namespace `HQPipeline`:
  - `listRuns(filters)` → GET /api/pipeline/runs
  - `createRun(data)` → POST /api/pipeline/runs
  - `getRun(id)` → GET /api/pipeline/runs/{id}
  - `approveRun(id)` → POST /api/pipeline/runs/{id}/approve
  - `pauseRun(id)`, `resumeRun(id)`, `abortRun(id)`
  - `connectWebSocket(runId, onEvent)` — реальное-время
- Все вызовы используют `hqAuthHeaders()` из `_components.js`

**Estimate:** M (60 минут)
**Depends-on:** T-4-007

---

### T-4-009: Добавить пункт в sidebar

**Type:** ui
**Files:** `ai_agency/static/hq/_components.js`
**Acceptance:**
- В `SIDEBAR_ITEMS` (или где определён массив) добавлен:
  ```javascript
  {
    label: 'AI Pipeline',
    path: 'pipeline.html',
    icon: 'cpu',
    roles: ['owner']
  }
  ```
- Закомментировать пункт **«AI Команда»** или переименовать в «AI Команда (legacy)» — пока не удаляем
- Проверить что новый пункт видим только владельцу

**Estimate:** S (15 минут)
**Depends-on:** T-4-008

---

### T-4-010: Telegram уведомления (extension существующего бота)

**Type:** feature
**Files:** `ai_agency/telegram_bot.py` (минимальные правки)
**Acceptance:**
- Добавить функцию `send_pipeline_notification(run_id, event_type, message)` в telegram_bot.py
- Подписаться на `pipeline_events` через background task в main.py:
  ```python
  async def watch_pipeline_events():
      last_id = await get_last_processed_event_id()
      while True:
          new_events = await db.fetch_all(
              "SELECT * FROM pipeline_events WHERE id > ? AND event_type IN ('phase_completed','approval_needed','rate_limit_hit','paused','done','failed')",
              [last_id]
          )
          for event in new_events:
              await send_pipeline_notification(...)
              last_id = event.id
          await asyncio.sleep(5)
  ```
- Не трогать существующие команды бота
- Закоммитить

**Estimate:** M (60 минут)
**Depends-on:** T-4-009

---

### T-4-011: Mobile adaptation

**Type:** ui
**Files:** `ai_agency/static/hq/pipeline.html`, `pipeline-run-detail.html`, `hq-mobile.css`
**Acceptance:**
- На mobile (<768px) карточки pipeline-runs стекаются вертикально
- Модалка создания — bottom sheet
- Detail page — табы превращаются в swipeable horizontal scroll
- Кнопки управления — bottom sticky bar
- Тестирование через Chrome DevTools mobile preview

**Estimate:** M (60 минут)
**Depends-on:** T-4-010

---

### T-4-012: Полный E2E test

**Type:** test
**Files:** `ai_agency/tests/test_pipeline_e2e.py`
**Acceptance:**
- Тест:
  1. Создать pipeline-run через HQ UI (или через API)
  2. Дождаться завершения (60-120 минут!)
  3. Проверить что:
     - `pipeline_runs.status` = 'review'
     - Все фазы прошли (events)
     - В workspace есть код проекта
     - `pnpm build` (или эквивалент) проходит в workspace
     - GitHub-ветка создана и запушена
- Это **дорогой тест** — использует много токенов

**Estimate:** L (90 минут + 2 часа на выполнение)
**Depends-on:** T-4-011

---

## Definition of done for sprint 4

- [ ] Все задачи T-4-001..T-4-012 выполнены
- [ ] Phases 5-7 работают (реальное выполнение спринтов)
- [ ] Rate limit handling с downgrade работает
- [ ] HQ UI: pipeline.html + pipeline-run-detail.html
- [ ] WebSocket live updates на UI
- [ ] Telegram уведомления о ключевых событиях
- [ ] Mobile adaptation
- [ ] E2E test проходит для простого landing

## Acceptance demo

После Sprint 4:

1. Зайти в HQ → AI Pipeline → «Новый pipeline-run»
2. Ввести: «Простой landing для AI-агентства с CTA на Telegram», type=landing, autonomy_level=2
3. Нажать «Запустить»
4. На странице run-а видно прогресс
5. После Phase 4 — приходит Telegram «🔔 План спринтов готов, нужно одобрение»
6. Нажать «Approve» в HQ
7. Pipeline идёт дальше, иногда уведомляет о rate limit паузах
8. Через 2-3 часа — Telegram «🎉 Pipeline #1 готов к review. Preview: https://..."
9. Открыть preview URL — работающий landing
10. В git репо ветка `pipeline/1-final` готова к merge

## Что НЕ делаем в Sprint 4

- НЕ строим полноценный чат с pipeline (это v1.1 backlog)
- НЕ деплоим в продакшен (только preview)
- НЕ трогаем старую AI Команду (это Sprint 5)
- НЕ оптимизируем токены за рамками базового downgrade

## Известные риски

- **Phase 5 — самая нестабильная.** Реальные builders могут писать плохой код, скорее всего понадобится несколько итераций калибровки.
- **Лимиты Max.** Полный E2E может съесть 30-50% недельного Opus. Запускать с осознанием.
- **GitHub auth.** Pipeline должен иметь возможность пушить. Решение: SSH key на сервере + добавлен в deploy keys репо.
- **WebSocket reconnect.** Если фронт теряет коннект — нужно реконнектиться и подгружать пропущенные события через `?since=`. Если в первой итерации UI не идеальный — не страшно.
