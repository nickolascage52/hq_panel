"""Phase 3 — Architecture decision (T-3-009, Sprint 3).

Calls Claude with /architecture-decider skill. Expects /docs/ARCHITECTURE.md
and /CLAUDE.md to be written. If autonomy_level < 3, raises ApprovalRequired
to pause for owner approval.

Stub mode (PIPELINE_FORCE_STUB=true) — sleeps 2s.
"""
from __future__ import annotations

import asyncio
import logging
import os

from ..claude_runner import ClaudeRunner
from ..exceptions import ApprovalRequired, PhaseExecutionError
from .base import PhaseBase

logger = logging.getLogger(__name__)

ARCH_TASK = """\
Read /docs/PRD.md and /agency/standards/{project_type}.md (if exists). Use
the /architecture-decider skill to produce:

1. /docs/ARCHITECTURE.md — full architecture decision record
2. /CLAUDE.md — project rules for the agents that will build subsequent sprints

Reply with one line: "ARCHITECTURE + CLAUDE.md written. Stack: <one-line summary>".
Do not chat.
"""


class Phase3Architecture(PhaseBase):
    name = "architecture"

    async def _run(self) -> None:
        if os.getenv("PIPELINE_FORCE_STUB") == "true":
            await asyncio.sleep(2)
            return

        run = self.runner.run_data
        arch_path = self.runner.workspace.docs_path / "ARCHITECTURE.md"
        claude_md = self.runner.workspace.path / "CLAUDE.md"

        runner = ClaudeRunner(self.runner.run_id)
        async for _ in runner.run_agent(
            workspace_path=str(self.runner.workspace.path),
            agent_persona="architecture-decider",
            prompt=ARCH_TASK.format(project_type=run.get("project_type", "custom")),
            model="opus",
            timeout=900,
        ):
            pass

        if not arch_path.exists() or arch_path.stat().st_size < 500:
            raise PhaseExecutionError("ARCHITECTURE.md missing or empty", phase_name=self.name)
        if not claude_md.exists() or claude_md.stat().st_size < 200:
            raise PhaseExecutionError("CLAUDE.md missing or empty", phase_name=self.name)
        logger.info("Phase3: ARCHITECTURE.md (%d) + CLAUDE.md (%d) ready",
                    arch_path.stat().st_size, claude_md.stat().st_size)

        # Approval gate (autonomy_level < 3 → wait for owner)
        autonomy = int(run.get("autonomy_level") or 2)
        if autonomy < 3:
            raise ApprovalRequired(
                "Architecture ready, awaiting owner approval before sprint planning",
                phase_name=self.name,
            )
