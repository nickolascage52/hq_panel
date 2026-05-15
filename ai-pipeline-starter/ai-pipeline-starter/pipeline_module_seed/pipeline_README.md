# Pipeline Module Seed

This folder is a **reference** showing what `ai_agency/pipeline/` will look like once Sprint 2-4 are complete. It is NOT working code — it's a target structure for Claude Code to build toward.

## Target structure inside `ai_agency/pipeline/`

```
pipeline/
├── __init__.py                  # exports: PipelineRunner, resume_pending_runs
├── runner.py                    # PipelineRunner — main coordinator
├── workspace.py                 # PipelineWorkspace — manages /pipeline_workspaces/<id>/
├── progress.py                  # PipelineProgress — events + websocket broadcast
├── claude_runner.py             # claude-agent-sdk wrapper
├── tmux_manager.py              # tmux session control
├── git_manager.py               # git init, worktree, commit, push
├── rate_limit.py                # RateLimitManager + downgrade logic
├── queue.py                     # PipelineQueue — 1 active run at a time
├── deploy.py                    # deploy strategies (none/vercel/aeza)
├── exceptions.py                # PipelineError + subclasses
├── types.py                     # ProjectType, RunStatus enums + dataclasses
└── phases/
    ├── __init__.py
    ├── base.py                  # PhaseBase abstract
    ├── phase1_prompt.py         # Prompt refinement (uses /prompt-forge skill)
    ├── phase2_prd.py            # PRD generation (uses /prd-builder skill)
    ├── phase3_architecture.py   # Architecture decision
    ├── phase4_sprints.py        # Sprint planning
    ├── phase5_execution.py      # Sprint execution (architect + builders + validator)
    ├── phase6_validation.py     # Final validation
    └── phase7_handoff.py        # Final report + Telegram + deploy
```

## Files to be added at the project root

```
ai_agency/
├── pipeline/                    # ↑ above
├── pipeline_api.py              # FastAPI routes — navешивается на app в main.py
├── pipeline_workspaces/         # runtime: workspaces for each pipeline-run
│   └── <run_id>/                # auto-created per run
└── static/hq/
    ├── pipeline.html            # list + create UI
    ├── pipeline-run-detail.html # detail view
    └── hq-pipeline.js           # JS module
```

## New tables in agency.db

See `pipeline_sql_seed.sql` in this folder for the SQL.

- `pipeline_runs` — main entity
- `pipeline_sprints` — sprints within a run
- `pipeline_events` — event log
- `pipeline_chat_messages` — chat history per run
- `pipeline_rate_limits` — current limits state
- `hq_sessions` — DB-backed sessions (replaces in-memory _sessions dict)

## Integration with existing tables

Pipeline uses existing tables where they already fit:

| Existing | How pipeline uses it |
|----------|----------------------|
| `delivery_projects` | One entry per pipeline-run (FK from `pipeline_runs.delivery_project_id`) |
| `delivery_stages` | Mirror of `pipeline_sprints` for HQ UI display |
| `delivery_tasks` | Atomic tasks within a sprint (uses `branch_name`, `pull_request_url`, etc.) |
| `delivery_templates` | Used by Phase 4 to seed sprint structure |
| `executors` | Pipeline agent personas registered with `level='ai_pipeline_worker'` |
| `agent_executions` | Every Claude SDK call logged here |
| `knowledge_base` | Project briefs uploaded by owner |
| `hq_users.github_username` | Used for PR review attribution |

## How everything wires together

```
HQ panel: /hq/pipeline.html
       │
       │ POST /api/pipeline/runs { idea, type, autonomy, deploy }
       ↓
pipeline_api.py
       │
       │ creates pipeline_runs row
       │ creates delivery_project (or links existing)
       │ creates workspace dir
       │ asyncio.create_task(PipelineRunner(run_id).execute())
       │
       ↓
PipelineRunner.execute()
       │
       ├─ Phase 1: prompt refinement (claude_runner + /prompt-forge skill)
       ├─ Phase 2: PRD (claude_runner + /prd-builder skill)
       ├─ Phase 3: Architecture (+ /architecture-decider)
       ├─ Phase 4: Sprints (+ /sprint-planner) → creates pipeline_sprints + delivery_stages
       │
       │ [pause for approval if autonomy_level < 3]
       │
       ├─ Phase 5: For each sprint:
       │     ├─ tmux session create
       │     ├─ spawn architect (Opus) → contracts
       │     ├─ spawn builders (Sonnet) in worktrees → code
       │     ├─ spawn validator (Haiku) → tests + lint
       │     ├─ spawn code-reviewer (Sonnet)
       │     ├─ spawn prd-compliance-checker (Opus)
       │     └─ commit + push
       │
       ├─ Phase 6: Final validation
       └─ Phase 7: Handoff
             ├─ Generate /docs/final-report.md
             ├─ Deploy to preview (if strategy != 'none')
             ├─ Update delivery_projects.status = 'На проверке'
             └─ Telegram: 🎉 done
```

Events at every step → `pipeline_events` → WebSocket → HQ UI live update + Telegram bridge.

## Workspace structure (per pipeline-run)

```
pipeline_workspaces/<run_id>/
├── .git/                        # separate repo per run
├── CLAUDE.md                    # project rules for THIS client project
├── docs/
│   ├── prompt.md                # Phase 1 output
│   ├── PRD.md                   # Phase 2 output
│   ├── ARCHITECTURE.md          # Phase 3 output
│   ├── sprints/
│   │   ├── _index.md
│   │   ├── sprint-1-*.md        # Phase 4 outputs
│   │   └── ...
│   ├── contracts/
│   │   ├── sprint-1/            # architect outputs per sprint
│   │   └── ...
│   ├── overseer-log.md          # decisions log
│   └── final-report.md          # Phase 7 output
├── .claude/
│   └── agents/                  # copied from agency/standards/<type>/agents/
└── (generated client project code: Next.js / bot / etc)
```

## See also

- `/docs/PRD.md` — what pipeline does
- `/docs/ARCHITECTURE.md` — how it's built
- `/docs/sprints/_index.md` — implementation roadmap
- `/CLAUDE.md` — rules for implementation
