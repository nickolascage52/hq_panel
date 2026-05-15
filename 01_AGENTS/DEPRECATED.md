# Shell Agents — Status as of v1.0 (2026-05-15)

These per-agent SYSTEM_PROMPT.md files were used by an earlier
**shell-agents** prototype: separate Claude Code sessions launched via
`scripts/01..12_*.sh` and `launch_agents.sh` from the project root. Each
session ran a single agent with one of these prompts.

## Status

- **Not deprecated** — these prompts are still useful as REFERENCE for the
  voice and constraints of the agency's content/research/product roles.
- **Not used by code anymore.** The runtime AI Team (Sprint 1-2 era) lives
  in `ai_agency/agents/team.py` (Python classes) — those are what
  `orchestrator.py` and `telegram_bot.py` call.
- **Not used by AI Pipeline.** The new pipeline (Sprint 2-4) uses Claude
  Code agents from `~/.claude/agents/` (per-user) and skill templates from
  `agency/standards/skills/` (in repo).

## Decision

Keep these `01_AGENTS/<agent>/SYSTEM_PROMPT.md` files as **canonical
agency role definitions**:
- New runtime agents (Python classes or Claude Code personas) should mirror
  the role/voice defined here.
- Manual reference when training new team members or external contractors.

Do NOT delete in v1.0. Re-evaluate in v2.0 if any are duplicates of newer
canonical sources.

## See also

- `ai_agency/agents/team.py` — current runtime agents
- `agency/standards/` — agency-wide standards used by AI Pipeline
- `scripts/` — old launch scripts (also kept as reference, see scripts/README.md)
