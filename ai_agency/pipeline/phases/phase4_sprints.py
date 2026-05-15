"""Phase 4 — Sprint planning (T-3-011, Sprint 3).

Calls Claude with /sprint-planner skill. Expects sprint files written under
/docs/sprints/. Reads them, populates pipeline_sprints (and mirror
delivery_stages if delivery_project_id is set).

If autonomy_level < 2, raises ApprovalRequired after writing.

Stub mode (PIPELINE_FORCE_STUB=true) — sleeps 2s.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

import aiosqlite

from database import DB_PATH

from ..claude_runner import ClaudeRunner
from ..exceptions import ApprovalRequired, PhaseExecutionError
from .base import PhaseBase

logger = logging.getLogger(__name__)

SPRINTS_TASK = """\
Read /docs/PRD.md and /docs/ARCHITECTURE.md from this workspace. Use the
/sprint-planner skill to slice the project into sprints.

Output:
- /docs/sprints/_index.md — overview of all sprints
- /docs/sprints/sprint-N-<slug>.md — one file per sprint (3-7 sprints total)

Reply with one line: "Sprint plan: N sprints, M tasks total". Do not chat.
"""

SPRINT_FILE_RE = re.compile(r"^sprint-(\d+)-(.+)\.md\$")


class Phase4Sprints(PhaseBase):
    name = "sprints"

    async def _run(self) -> None:
        if os.getenv("PIPELINE_FORCE_STUB") == "true":
            await asyncio.sleep(2)
            return

        run = self.runner.run_data
        sprints_dir = self.runner.workspace.docs_path / "sprints"

        runner = ClaudeRunner(self.runner.run_id)
        async for _ in runner.run_agent(
            workspace_path=str(self.runner.workspace.path),
            agent_persona="sprint-planner",
            prompt=SPRINTS_TASK,
            model="opus",
            timeout=900,
        ):
            pass

        if not sprints_dir.exists():
            raise PhaseExecutionError("docs/sprints/ not created", phase_name=self.name)

        sprint_files = await asyncio.to_thread(_collect_sprint_files, sprints_dir)
        if len(sprint_files) < 1:
            raise PhaseExecutionError(
                "No sprint files found in docs/sprints/", phase_name=self.name,
            )

        # Persist to DB
        delivery_project_id = run.get("delivery_project_id")
        async with aiosqlite.connect(str(DB_PATH)) as db:
            for sprint_num, slug, path in sprint_files:
                spec = await asyncio.to_thread(path.read_text, "utf-8")
                title_match = re.search(r"^#\s+(.+)\$", spec, re.MULTILINE)
                name = title_match.group(1).strip() if title_match else slug
                await db.execute(
                    """
                    INSERT OR REPLACE INTO pipeline_sprints
                        (run_id, sprint_number, name, spec_md, status)
                    VALUES (?, ?, ?, ?, 'planned')
                    """,
                    (self.runner.run_id, sprint_num, name, spec),
                )
                # Mirror in delivery_stages (if linked to a delivery_project)
                if delivery_project_id:
                    await db.execute(
                        """
                        INSERT INTO delivery_stages
                            (project_id, name, description, status, stage_order)
                        VALUES (?, ?, ?, 'planned', ?)
                        """,
                        (delivery_project_id, name, f"Sprint {sprint_num}", sprint_num),
                    )
            await db.commit()

        logger.info("Phase4: persisted %d sprints (delivery_project_id=%s)",
                    len(sprint_files), delivery_project_id)

        autonomy = int(run.get("autonomy_level") or 2)
        if autonomy < 2:
            raise ApprovalRequired(
                "Sprint plan ready, awaiting owner approval before execution",
                phase_name=self.name,
            )


def _collect_sprint_files(sprints_dir: Path) -> list[tuple[int, str, Path]]:
    """Return [(sprint_number, slug, path), ...] sorted by sprint_number."""
    out = []
    for entry in sprints_dir.iterdir():
        if not entry.is_file():
            continue
        m = SPRINT_FILE_RE.match(entry.name)
        if not m:
            continue
        out.append((int(m.group(1)), m.group(2), entry))
    out.sort(key=lambda t: t[0])
    return out
