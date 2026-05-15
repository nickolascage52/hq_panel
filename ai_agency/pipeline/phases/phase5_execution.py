"""Phase 5 — Sprint execution loop (T-4-002, Sprint 4).

Iterates pipeline_sprints for the current run, marks each as active/done.
Real implementation (spawn architect/builders/validator via Claude Code in
tmux + git worktrees) is in v1.1 backlog — needs ANTHROPIC_API_KEY restored.

Sprint 4 v1.0 stub: per-sprint sleep + status update + events emission.
Captures the orchestration shape so UI can render progress and so the rest
of the pipeline (Phase 6/7) can run end-to-end with stub mode.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import aiosqlite

from database import DB_PATH

from ..exceptions import RateLimitExceeded
from ..rate_limit import RateLimitManager
from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase5Execution(PhaseBase):
    name = 'execution'

    async def _run(self) -> None:
        run_id = self.runner.run_id
        sprints = await self._load_sprints(run_id)

        if not sprints:
            logger.warning('Phase5: no sprints for run %s — short stub', run_id)
            if os.getenv('PIPELINE_FORCE_STUB') == 'true':
                await asyncio.sleep(2)
            return

        rate_limit = RateLimitManager()
        if await rate_limit.should_pause():
            raise RateLimitExceeded(
                'all models over weekly threshold',
                resume_after=await rate_limit.get_resume_estimate(),
            )

        sleep_each = 0.3 if os.getenv('PIPELINE_FORCE_STUB') == 'true' else 1.0

        for sprint in sprints:
            sprint_id = sprint['id']
            sprint_no = sprint['sprint_number']
            sprint_name = sprint['name']

            await self._mark_sprint(sprint_id, 'active')
            await self.runner.progress.emit_event(
                'sprint_started',
                payload={'sprint_id': sprint_id, 'sprint_number': sprint_no, 'name': sprint_name},
                sprint_id=sprint_id,
            )

            # Stub: simulate work. Real impl: spawn architect+builders+validator.
            await asyncio.sleep(sleep_each)

            await self._mark_sprint(sprint_id, 'done')
            await self.runner.progress.emit_event(
                'sprint_completed',
                payload={'sprint_id': sprint_id, 'sprint_number': sprint_no},
                sprint_id=sprint_id,
            )
            logger.info('Phase5: sprint %d (%s) marked done', sprint_no, sprint_name)

    async def _load_sprints(self, run_id: int) -> list[dict]:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                'SELECT id, sprint_number, name, status FROM pipeline_sprints '
                'WHERE run_id = ? ORDER BY sprint_number',
                (run_id,),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _mark_sprint(self, sprint_id: int, status: str) -> None:
        ts = datetime.now().isoformat(sep=' ', timespec='seconds')
        col = 'started_at' if status == 'active' else 'completed_at'
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                f'UPDATE pipeline_sprints SET status = ?, {col} = ? WHERE id = ?',
                (status, ts, sprint_id),
            )
            await db.commit()
