"""Phase 1 — Prompt refinement (T-3-005, Sprint 3).

Reads pipeline_runs.raw_idea, produces production_prompt:
- If raw_idea is already detailed (>500 chars), use as-is.
- Otherwise call Claude via ClaudeRunner to expand it.

Saves result to:
- pipeline_runs.production_prompt (DB column)
- <workspace>/docs/prompt.md (file in pipeline workspace)

Stub mode (PIPELINE_FORCE_STUB=true) — skips Claude call, sleeps 2s.
"""
from __future__ import annotations

import asyncio
import logging
import os

import aiosqlite

from database import DB_PATH

from ..claude_runner import ClaudeRunner
from .base import PhaseBase

logger = logging.getLogger(__name__)

EXPAND_PROMPT_TEMPLATE = """\
You are a senior product specialist at an AI agency. The owner gave us this
short idea for a client project:

<idea>
{raw_idea}
</idea>

Project type: {project_type}

Your job: produce a production-ready prompt that the next Claude agent
(/prd-builder) can use to write a complete PRD. The prompt must be:

1. Specific (target user, key value prop, channels, deliverables)
2. Constrained (what's in / out of scope, deploy strategy: {deploy_strategy})
3. Inspiration-rich (3-5 questions the agent should answer in the PRD)

Length: 600-1200 words. Russian if the idea is in Russian, English otherwise.

Write ONLY the production prompt — no preamble, no chat. Save it to
/docs/prompt.md and reply with one line: "prompt.md ready (N chars)".
"""


class Phase1Prompt(PhaseBase):
    name = "prompt"

    async def _run(self) -> None:
        if os.getenv("PIPELINE_FORCE_STUB") == "true":
            await asyncio.sleep(2)
            return

        run = self.runner.run_data
        raw_idea = (run.get("raw_idea") or "").strip()

        if len(raw_idea) >= 500:
            logger.info("Phase1: raw_idea is detailed (%d chars), bypassing Claude",
                        len(raw_idea))
            await self._save(raw_idea)
            return

        prompt = EXPAND_PROMPT_TEMPLATE.format(
            raw_idea=raw_idea,
            project_type=run.get("project_type", "custom"),
            deploy_strategy=run.get("deploy_strategy", "none"),
        )
        runner = ClaudeRunner(self.runner.run_id)
        chunks: list[str] = []
        async for ev in runner.run_agent(
            workspace_path=str(self.runner.workspace.path),
            agent_persona="prompt-forge",
            prompt=prompt,
            model="opus",
            timeout=600,
        ):
            if ev.get("text"):
                chunks.append(ev["text"])

        prompt_md_path = self.runner.workspace.docs_path / "prompt.md"
        if prompt_md_path.exists():
            production_prompt = prompt_md_path.read_text(encoding="utf-8")
        else:
            production_prompt = "\n".join(chunks).strip()
            prompt_md_path.write_text(production_prompt, encoding="utf-8")

        await self._save(production_prompt)

    async def _save(self, production_prompt: str) -> None:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                "UPDATE pipeline_runs SET production_prompt = ? WHERE id = ?",
                (production_prompt, self.runner.run_id),
            )
            await db.commit()
        prompt_md = self.runner.workspace.docs_path / "prompt.md"
        prompt_md.parent.mkdir(parents=True, exist_ok=True)
        prompt_md.write_text(production_prompt, encoding="utf-8")
