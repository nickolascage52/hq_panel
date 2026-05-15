# Shell Agent Launch Scripts — DEPRECATED v1.0

The 12 numbered scripts here (`01_chief_of_staff.sh` ... `12_qa_agent.sh`)
plus `../launch_agents.sh` were part of an earlier prototype that launched
Claude Code sessions per agent persona via tmux.

## Status

- **Not used by current code** — runtime AI Team is in
  `ai_agency/agents/team.py`; AI Pipeline (Sprint 2-4) uses
  `ai_agency/pipeline/`.
- **Kept as reference** — same reasoning as `01_AGENTS/DEPRECATED.md`:
  the persona definitions and tmux launch patterns may inform v2.0
  pipeline design (especially the Phase 5 "spawn agents in tmux"
  flow that's still in v1.1 backlog).

## Do NOT run these scripts on prod

They expect a Claude Code CLI that may not be installed on the production
server, and they don't integrate with `pipeline_runs` or `pipeline_events`
tracking.

For pipeline runs, use the new path:
- HQ panel → AI Pipeline → Новый pipeline-run
- Or POST /api/pipeline/runs (see `docs/sprint-3-final-report.md`)

## Removal

To be re-evaluated in v2.0 — if Phase 5 real implementation in v1.1 absorbs
the patterns, we can delete then.
