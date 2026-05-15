# CLAUDE.md — Project Rules for AI Pipeline Implementation

This file is loaded automatically by Claude Code when working in this project. It defines rules and conventions for any AI agent working on the codebase.

## Project context

You are working on **AI Delivery HQ** — an internal operations system for an AI agency. We are adding a new module: **AI Pipeline** for autonomous client project development.

## Source of truth (read these FIRST)

Before doing anything, read in this order:

1. `ai_agency/CLAUDE.md` — existing detailed project context (~25KB, critical reading)
2. `docs/PRD.md` — what we're building and why
3. `docs/ARCHITECTURE.md` — how we're building it
4. `docs/sprints/_index.md` — sprint overview
5. `docs/sprints/sprint-N-*.md` — current sprint (replace N with active sprint number)
6. `docs/audit-2026-05-15.md` — full audit of existing codebase

## Stack (LOCKED for this project)

- **Backend:** FastAPI 0.110, Python 3.13, aiosqlite, anthropic>=0.40,<1
- **AI integration:** claude-agent-sdk
- **DB:** SQLite (existing `agency.db`) with WAL mode
- **Frontend:** Vanilla JS + CSS, NO frameworks
- **Git:** GitPython or subprocess
- **Process management:** tmux + asyncio.subprocess

Do not introduce React, Vue, Postgres, Redis, Celery, or any other technology not listed here. The project is intentionally minimalist — keep it that way.

## File structure conventions

### What you can create/modify freely

- `ai_agency/pipeline/*` — new module, full freedom within stack
- `ai_agency/pipeline_api.py` — new file for pipeline endpoints
- `ai_agency/static/hq/pipeline.html`, `pipeline-run-detail.html`, `hq-pipeline.js` — new UI
- `agency/standards/*` — agency standards documents
- `docs/*` — documentation
- `.claude/agents/*` — agent personas (this directory in the project root)
- Tests in `ai_agency/tests/`

### What you can modify with caution

- `ai_agency/database.py` — only ADD new tables/migrations, never modify existing
- `ai_agency/main.py` — only ADD imports/calls for new module
- `ai_agency/static/hq/_components.js` — only ADD pipeline menu item

### What you must NOT touch

- `ai_agency/orchestrator.py` — old AI team coordinator (until Sprint 5)
- `ai_agency/agents/*` — old 23 AI agents (until Sprint 5)
- `ai_agency/telegram_bot.py` — depends on orchestrator (until Sprint 5)
- `ai_agency/api.py` — only when explicitly required by a task
- `ai_agency/hq_v3_api.py` — only when explicitly required
- Anything else in `ai_agency/static/hq/*.html` — these are existing pages, leave them alone unless task requires
- `.env`, `.env.example` — only modify in Sprint 1

## Critical rules

### 1. Git workflow

- Work in feature branches: `git checkout -b feature/sprint-N/task-name`
- Commit AFTER each task with message: `[T-N-XXX] short description`
- Push branch to remote
- Create PR to main via GitHub
- Wait for human review before merging (Sprint 1 — even more careful)

### 2. Database migrations

- All migrations through `database.py:init_db()` — idempotent
- Use `CREATE TABLE IF NOT EXISTS`, `_add_column_if_missing`
- Test migration twice: fresh DB + existing DB
- Never break backward compatibility with existing schema

### 3. Auth

- Use `require_role(['owner'])` for all pipeline endpoints
- Never trust `agent_name` or other fields from request body without validation
- All pipeline actions are owner-only in v1

### 4. Long-running tasks

- All long pipeline operations via `asyncio.create_task()`
- State in DB, not in memory
- Make operations resumable after restart

### 5. Error handling

- Use custom exceptions from `pipeline/exceptions.py`
- Log errors with context (run_id, sprint_id, phase)
- Pipeline failures = pause + Telegram alert, never silent

### 6. Testing

- E2E tests for each sprint in `ai_agency/tests/test_pipeline_*.py`
- Smoke test all HQ pages after sprint completion
- Run `_release_gate_test.py` before sprint completion

### 7. Mobile

- All new UI must work on mobile (<768px)
- Test in Chrome DevTools mobile preview
- Bottom sheets for modals, FAB for primary actions

## Coding style

- **Type hints**: required in all new Python code
- **Async/await**: no blocking calls in event loop
- **Logging**: `logger = logging.getLogger(__name__)` at module top
- **Imports**: stdlib → third-party → local
- **Naming**: snake_case files/functions, PascalCase classes, UPPER_SNAKE constants
- **No comments** explaining what code does — comments explain WHY when non-obvious

## Plan Mode

For any sprint, **start in Plan Mode** (Shift+Tab twice in Claude Code):
1. Read all source-of-truth documents
2. Read current sprint file
3. Form a plan: which tasks first, what files to read, what to create
4. Show plan to user, wait for "go"
5. Only then execute

## Working with multi-agent (Sprint 3+)

When using subagents:
- Architect (Opus) FIRST — fixes contracts before builders start
- Builders (Sonnet) work in worktrees, in parallel by domain
- Validator (Haiku) after each task
- Never spawn more than 5 agents in one tmux session

## When uncertain

If something in the sprint is ambiguous:
1. Re-read PRD and ARCHITECTURE
2. Re-read existing code (`ai_agency/CLAUDE.md`, codebase grep)
3. If still unclear — STOP, ask the user

Never guess. Never invent stack choices not in this file.

## Sprint completion checklist

Before declaring a sprint done:
- [ ] All tasks in sprint file checked off
- [ ] All commits in feature branches merged to main
- [ ] Sprint-specific E2E test passes
- [ ] `_release_gate_test.py` passes (if applicable)
- [ ] HQ smoke test (open each page, verify it works)
- [ ] Sprint retrospective notes added to sprint file (what went well, what didn't)

## Communication

- Updates to user via the active Telegram channel if running with `--channels`
- Otherwise — terminal output is fine
- Write to `docs/overseer-log.md` after major decisions (audit trail)

## Important grottoes (from audit)

- **In-memory sessions** existed before Sprint 1 — verify they're now in `hq_sessions` table before depending on session persistence in pipeline
- **SQLite locks** — pipeline may hit `database is locked` if not careful. Always WAL mode, use short transactions
- **`delivery.html`** was broken in audit — verify it's fixed before relying on `delivery_*` table UI
- **Old AI team is fragile** — Telegram bot depends on it. Sprint 1-4 must not touch it
- **`anthropic>=0.40,<1`** is locked — DO NOT upgrade, breaks compatibility

## Final note

The goal is **production-ready, maintainable code that integrates cleanly with existing HQ**. Not perfect code. Not minimal code. Code that the owner can run, debug, extend, and trust.
