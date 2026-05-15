# AI Delivery HQ + AI Pipeline Module

Internal operations platform for an AI agency, plus an autonomous client-project
generation pipeline built on Claude Code.

[![Release](https://img.shields.io/badge/release-v1.0.0-blue)]()
[![Stack](https://img.shields.io/badge/python-3.13-blue)]()
[![Stack](https://img.shields.io/badge/fastapi-0.136-009688)]()
[![Status](https://img.shields.io/badge/status-private-red)]()

---

## What this is

Two systems in one repo:

1. **AI Delivery HQ** (`ai_agency/`) — operational core of the agency:
   FastAPI + SQLite + Telegram bot + 23 prompt-based AI agents + vanilla
   HTML/JS panel. Manages CRM, projects, students, content, analytics.
   Lives in production at `89.22.235.144`.

2. **AI Pipeline Module** (`ai_agency/pipeline/`) — autonomous client
   project development. Owner enters an idea, pipeline goes through 7
   phases (prompt refinement → PRD → architecture → sprint plan → execution
   → validation → handoff) using Claude Code multi-agent.

The pipeline module was built across Sprint 1-5 (see `docs/sprint-N-final-report.md`).

## Quick start

### Local development (Windows + venv)

```powershell
cd ai_agency
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Set up .env (copy from .env.example, fill real values)
copy .env.example .env
notepad .env

# Optional: PYTHONIOENCODING=utf-8 to avoid cp1251 console issues
$env:PYTHONIOENCODING = "utf-8"
$env:WEB_ONLY = "true"  # skip Telegram bot + scheduler locally
.\venv\Scripts\python.exe main.py
```

Open `http://127.0.0.1:8000/hq/` and log in with `ADMIN_PASSWORD` from `.env`.

### Production (Linux + systemd, current setup)

The production server is `89.22.235.144` running systemd unit `ai-agency`
(see `ai_agency/install.sh` and `ai_agency/setup_nginx.sh`). To deploy
updates after a `git pull`:

```bash
cd /var/www/ai_agency/ai_agency
git pull origin main
pip install -r requirements.txt   # pick up any new deps
systemctl restart ai-agency
systemctl status ai-agency
tail -f /var/log/ai-agency.log    # check first 30 sec for errors
```

Full first-time deploy of the v1.0 changes (Sprint 1-5) — see
`docs/deploy-v1.0.md`.

## Repository layout

```
AI_Delivery_Team/
├── README.md                          # this file
├── CLAUDE.md                          # project instructions for Claude
├── .gitignore
├── 00_MASTER/ … 10_TMUX/              # agency knowledge (SOPs, templates, content)
├── agency/                            # standards used by AI Pipeline
│   └── standards/
│       ├── landing.md                 # stack convention for landing projects
│       └── skills/                    # SKILL.md templates (copy to ~/.claude/skills/)
├── ai_agency/                         # ⚡ operational core (Python)
│   ├── main.py                        # entry point: FastAPI + bot + scheduler
│   ├── api.py                         # main FastAPI (auth, CRM, content, projects)
│   ├── hq_v3_api.py                   # additional endpoints (delivery, executors, …)
│   ├── pipeline_api.py                # ★ NEW (v1.0): /api/pipeline/* endpoints
│   ├── database.py                    # all CREATE TABLE + migrations
│   ├── orchestrator.py                # legacy 23-agent coordinator
│   ├── telegram_bot.py                # Telegram bot
│   ├── scheduler.py                   # daily/weekly cycles
│   ├── session_store.py               # ★ NEW (v1.0): hq_sessions table backing
│   ├── agency_context_loader.py       # context with priority + 60s cache
│   ├── delivery_template_seed.py      # 8 project templates
│   ├── pipeline/                      # ★ NEW (v1.0): pipeline module
│   │   ├── runner.py                  # PipelineRunner.execute() / .resume()
│   │   ├── workspace.py               # /pipeline_workspaces/<id>/ management
│   │   ├── progress.py                # event log + WebSocket broadcast
│   │   ├── claude_runner.py           # claude-agent-sdk wrapper
│   │   ├── git_manager.py             # GitPython wrapper
│   │   ├── tmux_manager.py            # tmux subprocess wrapper
│   │   ├── rate_limit.py              # downgrade chains
│   │   ├── deploy.py                  # deploy strategies (none/vercel/aeza)
│   │   ├── telegram_notifier.py       # pipeline event → Telegram watcher
│   │   ├── exceptions.py
│   │   └── phases/                    # Phase 1-7 implementations
│   ├── agents/                        # legacy 23 prompt agents
│   ├── static/
│   │   ├── hq/                        # vanilla HTML/CSS/JS panel (20+ pages)
│   │   │   ├── pipeline.html              # ★ NEW (v1.0)
│   │   │   ├── pipeline-run-detail.html   # ★ NEW (v1.0)
│   │   │   └── hq-pipeline.js             # ★ NEW (v1.0)
│   │   └── admin/                     # DEPRECATED (use /hq/)
│   ├── tests/
│   │   ├── test_pipeline_skeleton.py  # ★ pipeline E2E (4 tests)
│   │   ├── test_pipeline_phases_1_4.py # ★ live phase 1-4 (skipif no API key)
│   │   ├── test_pipeline_e2e.py       # ★ full pipeline (skipif no API key)
│   │   └── e2e/                       # Playwright HQ smoke
│   ├── scripts/
│   │   └── rotate_backups.sh          # ★ NEW (v1.0): cron rotation
│   ├── data/agency_context.md         # uploaded agency context (priority 1)
│   ├── agency.db                      # SQLite (gitignored)
│   ├── requirements.txt
│   └── README_DEPLOY.md
├── docs/                              # ★ NEW (v1.0): all reports + plans
│   ├── audit-2026-05-15.md            # initial codebase audit
│   ├── PRD.md                         # what AI Pipeline does
│   ├── ARCHITECTURE.md                # how AI Pipeline is built (in starter)
│   ├── sprint-1-final-report.md       # … per-sprint reports
│   ├── sprint-2-…  through  sprint-5-final-report.md
│   ├── ai-team-deprecation-plan.md    # legacy AI Team plan
│   ├── backlog-v1.1.md                # what's deferred for v1.1
│   ├── deploy-v1.0.md                 # production deploy guide for v1.0 changes
│   └── dependency-decisions.md
├── ai-pipeline-starter/               # original starter pack (frozen for reference)
├── 01_AGENTS/ + scripts/              # DEPRECATED shell-agent prototypes
└── Кейсы/, Файлы агентства/, …        # business documents
```

## AI Pipeline at a glance

```
HQ panel: /hq/pipeline.html
   │
   │ POST /api/pipeline/runs { idea, type, autonomy, deploy }
   ↓
pipeline_api.py
   │
   │ INSERT pipeline_runs + asyncio.create_task(PipelineRunner.execute())
   ↓
PipelineRunner.execute() — 7 phases:
   1. Prompt refinement       (claude_runner + /prompt-forge)
   2. PRD generation          (/prd-builder skill → docs/PRD.md)
   3. Architecture decision   (/architecture-decider → ARCHITECTURE.md + CLAUDE.md)
   4. Sprint planning         (/sprint-planner → docs/sprints/*.md + DB rows)
       [pause for owner approval if autonomy_level<3]
   5. Sprint execution        (architect+builders+validator in tmux+worktrees)
       — orchestration scaffold in v1.0; real spawn in v1.1 backlog
   6. Final validation        (build/test/lint — stub in v1.0)
   7. Handoff                 (final-report.md + deploy + delivery_projects.status)

All events → pipeline_events DB table → WebSocket → HQ live UI + Telegram bridge.
```

See `ai_agency/CLAUDE.md` § «16-bis. AI Pipeline Module» for full detail.

## Tests

```powershell
cd ai_agency

# Stub-mode E2E (no Claude tokens, ~40 sec)
.\venv\Scripts\python.exe -m pytest tests\test_pipeline_skeleton.py -v

# Phases 1-4 against real Claude (requires ANTHROPIC_API_KEY, ~10-20 min)
.\venv\Scripts\python.exe -m pytest tests\test_pipeline_phases_1_4.py -v -s

# Full pipeline (~60-120 min, ~30-50% weekly Opus budget)
.\venv\Scripts\python.exe -m pytest tests\test_pipeline_e2e.py -v -s --timeout=10800
```

## Contributing / development

This is a single-owner project. Workflow:

1. Read `CLAUDE.md` and `ai_agency/CLAUDE.md` first
2. New work → `git checkout -b feature/<name>`
3. Test locally (`pytest tests/test_pipeline_skeleton.py` minimum)
4. Push + PR to main on GitHub
5. After merge: deploy via `git pull` on `89.22.235.144` + `systemctl restart ai-agency`

## Roadmap

- **v1.0** ✅ — released 2026-05-15. Caркас pipeline + HQ integration done.
- **v1.1** 🚧 — Phase 5 real spawn (architect+builders+validator), Phase 6
  real build/test, Vercel deploy, Pause/Resume/Abort UI, Documents/Sprints
  tabs. See `docs/backlog-v1.1.md`.
- **v2.0** — old AI Team final removal, multi-tenancy.

## License

Private — for internal agency use only.

---

_Built across 5 sprints + 65 tasks + 36 commits. See `docs/sprint-N-final-report.md` for the journey._
