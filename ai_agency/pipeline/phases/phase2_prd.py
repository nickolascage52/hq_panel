"""Phase 2 — PRD generation (T-3-007, Sprint 3).

Reads /docs/prompt.md, calls Claude with /prd-builder skill instruction,
expects /docs/PRD.md to be written. Verifies file exists and is non-trivial.

Stub mode (PIPELINE_FORCE_STUB=true) — sleeps 2s.
"""
from __future__ import annotations

import asyncio
import logging
import os

from ..claude_runner import ClaudeRunner
from ..exceptions import PhaseExecutionError
from .base import PhaseBase

logger = logging.getLogger(__name__)

PRD_TASK = """\
Read /docs/prompt.md from this workspace. It contains the production prompt
for the project. Use the /prd-builder skill to produce a complete PRD at
/docs/PRD.md. If /agency/standards/{project_type}.md exists in the parent
repo, reference its stack and conventions.

Reply with one line: "PRD written to /docs/PRD.md (N lines)". Do not chat.
"""


class Phase2PRD(PhaseBase):
    name = "prd"

    async def _run(self) -> None:
        if os.getenv("PIPELINE_FORCE_STUB") == "true":
            await asyncio.sleep(2)
            return

        run = self.runner.run_data
        prd_path = self.runner.workspace.docs_path / "PRD.md"

        runner = ClaudeRunner(self.runner.run_id)
        async for _ in runner.run_agent(
            workspace_path=str(self.runner.workspace.path),
            agent_persona="prd-builder",
            prompt=PRD_TASK.format(project_type=run.get("project_type", "custom")),
            model="opus",
            timeout=900,
        ):
            pass

        if not prd_path.exists() or prd_path.stat().st_size < 500:
            raise PhaseExecutionError(
                f"PRD.md missing or too small ({prd_path})",
                phase_name=self.name,
            )
        logger.info("Phase2: PRD.md ready (%d bytes)", prd_path.stat().st_size)
