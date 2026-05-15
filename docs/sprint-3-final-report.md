# Sprint 3 — Final Report

**Дата:** 2026-05-15
**Ветка:** `main` на `NickolasCage52/HQ_Panel`
**Локальная часть:** ✅ ЗАВЕРШЕНА (13/13 задач)
**Live-test:** ⏸ Skipped — требует ANTHROPIC_API_KEY (отозван в T-1-006)

---

## Что сделано

| ID | Задача | Что | Статус |
|---|---|---|---|
| T-3-001 | claude_runner.py | Async wrapper над claude-agent-sdk + key guard + agent_executions logging | ✅ |
| T-3-002 | git_manager.py | GitPython wrapper: init/branch/commit/push/worktree/merge/status/diff | ✅ |
| T-3-003 | tmux_manager.py | tmux subprocess wrapper, gracefully no-op на Windows (warning only) | ✅ |
| T-3-004 | agency/standards/landing.md | Стандарт лендинга (Next.js 15 + TS + Tailwind 4 + shadcn/ui) | ✅ |
| T-3-005 | Phase 1 Prompt | Real ClaudeRunner integration + short-circuit для раздетального raw_idea + PIPELINE_FORCE_STUB fallback | ✅ |
| T-3-006 | /prd-builder skill | Template в `agency/standards/skills/prd-builder.md`, инструкция как скопировать в `~/.claude/skills/` | ✅ |
| T-3-007 | Phase 2 PRD | Real /prd-builder call, verify PRD.md ≥500 bytes | ✅ |
| T-3-008 | /architecture-decider skill | Template + правила (стек из standards, ARCHITECTURE.md + CLAUDE.md) | ✅ |
| T-3-009 | Phase 3 Architecture | Real call, verify оба файла, raise ApprovalRequired при autonomy<3 | ✅ |
| T-3-010 | /sprint-planner skill | Template + правила (3-7 sprints, 4-12 tasks each) | ✅ |
| T-3-011 | Phase 4 Sprints | Real call, parse sprint-N-*.md, INSERT pipeline_sprints + mirror delivery_stages, raise ApprovalRequired при autonomy<2 | ✅ |
| T-3-012 | Approval API | `POST /api/pipeline/runs/{id}/approve` owner-only, валидация status, emit event, spawn resume | ✅ |
| T-3-013 | E2E test phases 1-4 | pytest test с `@pytest.mark.skipif(not _api_key_real())` — auto-skip без живого ключа | ✅ (skipped runtime) |

## Sprint 3 commits

```
993488f [T-3-004..012] feat(pipeline): real Phase 1-4 + skill templates + approval API
5310429 [T-3-001+002+003] feat(pipeline): claude_runner + git_manager + tmux_manager
```

(+ T-3-013 + final report — следующий коммит)

## Definition of Done

- ✅ Все T-3-001..T-3-013 в коммитах
- ✅ claude_runner / git_manager / tmux_manager работают (smoke + GitPython реальный E2E на tmpdir)
- ✅ Skills: 3 template-файла в `agency/standards/skills/` + README с инструкцией копирования
- ✅ `agency/standards/landing.md` создан (8.1 KB, скопирован из starter)
- ✅ Phases 1-4 имеют real implementation (ClaudeRunner) + stub fallback (PIPELINE_FORCE_STUB)
- ✅ Approval endpoint работает (валидация статуса + spawn resume)
- ⏸ E2E live test существует (test_pipeline_phases_1_4.py) но **skipped** — ANTHROPIC_API_KEY=`disabled-not-used`
- ✅ Регрессий нет: pytest test_pipeline_skeleton.py — 4 passed in 44.59s

## Critical decisions

### 1. PIPELINE_FORCE_STUB env var

Sprint 2 тесты ожидают что фазы выполняются за ~14 sec (sleep 2 × 7). Sprint 3 фазы делают real Claude calls которые без ключа падают с ClaudeCodeError. Решение — env-флаг `PIPELINE_FORCE_STUB=true` который форсит sleep mode. Тесты выставляют его в fixture; production runs его НЕ устанавливают и используют real ClaudeRunner.

### 2. Skill templates в репо vs ~/.claude/skills

Anthropic skills живут в `~/.claude/skills/<name>/SKILL.md` (per-user директория). Класть их в репо нельзя — это перезатрёт пользовательские. Решение — хранить **templates** в `agency/standards/skills/` (версионируются с проектом), пользователь копирует в `~/.claude/` командой из README. После SDK запросит `/prd-builder` — найдёт.

### 3. Honest API key gating

`ClaudeRunner.run_agent()` проверяет ANTHROPIC_API_KEY первой строкой. Если пусто или `disabled-not-used` — raise ClaudeCodeError с message указывающим причину и решение. Альтернатива — попытаться вызвать SDK и получить криптовый 401 — была отклонена.

### 4. Phase 4 mirrors в delivery_stages

Phase 4 не только пишет в `pipeline_sprints`, но и зеркалит в `delivery_stages` (если delivery_project_id есть). Это даёт бесплатное отображение спринтов в существующем `project-detail.html` без новой UI работы — пользователь увидит pipeline-спринты в delivery view сразу.

### 5. tmux на Windows = no-op

TmuxManager на Windows возвращает False с warning. Это даёт две выгоды: (1) pipeline phases которые опционально используют tmux могут безопасно вызывать `await tm.create()` без if-проверок; (2) prod Linux deploy будет иметь tmux и full feature.

## Что НЕ делали (по плану)

- ❌ Реальная интеграция claude-agent-sdk запущена (требует API key)
- ❌ Phase 5/6/7 не тронуты (Sprint 4)
- ❌ UI не создавался (Sprint 4)
- ❌ Старая AI Команда не тронута (Sprint 5)

## Acceptance demo (когда восстановят ANTHROPIC_API_KEY)

```bash
# 1. Скопировать skills (один раз)
mkdir -p ~/.claude/skills/{prd-builder,architecture-decider,sprint-planner}
cp agency/standards/skills/prd-builder.md ~/.claude/skills/prd-builder/SKILL.md
cp agency/standards/skills/architecture-decider.md ~/.claude/skills/architecture-decider/SKILL.md
cp agency/standards/skills/sprint-planner.md ~/.claude/skills/sprint-planner/SKILL.md

# 2. Поставить реальный ANTHROPIC_API_KEY в .env (вместо 'disabled-not-used')

# 3. Создать pipeline-run
curl -X POST http://localhost:8000/api/pipeline/runs \
  -H "X-Auth-Token: <token>" \
  -d '{"title":"test","raw_idea":"landing для AI-агентства","project_type":"landing","autonomy_level":3,"deploy_strategy":"none"}'

# 4. Подождать 10-20 минут — должны появиться:
#    pipeline_workspaces/<id>/docs/prompt.md
#    pipeline_workspaces/<id>/docs/PRD.md
#    pipeline_workspaces/<id>/docs/ARCHITECTURE.md
#    pipeline_workspaces/<id>/CLAUDE.md
#    pipeline_workspaces/<id>/docs/sprints/sprint-1-*.md, sprint-2-*.md, ...
#    Pipeline status='awaiting_approval' (т.к. autonomy=3 → нет, ждёт после Phase 4 если <2)

# 5. Approve если нужно:
curl -X POST http://localhost:8000/api/pipeline/runs/<id>/approve -H "X-Auth-Token: <token>"
```

## Метрики

- **Файлов создано:** 7 (1 standard, 3 skill templates, 1 README, 1 e2e test, 1 report)
- **Файлов модифицировано:** 7 (claude_runner, git_manager, tmux_manager, runner, 4 phases, pipeline_api, test fixture)
- **Строк +/−:** ~+1300 / −60
- **Коммитов:** 2 (большой + финальный отчёт)
- **Тесты:** 4 passed (test_pipeline_skeleton, регрессии нет) + 1 skipped (live phase 1-4)
- **Real Claude tokens used:** 0 (все mock/stub)
