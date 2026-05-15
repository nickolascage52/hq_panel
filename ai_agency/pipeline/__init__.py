"""AI Pipeline module — autonomous client project development.

Public exports:
    PipelineRunner          — main coordinator for one pipeline-run
    resume_pending_runs()   — called from main.py on startup to resume
                              runs that were running/paused before restart
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiosqlite

from database import DB_PATH

from .runner import PipelineRunner

__all__ = ["PipelineRunner", "resume_pending_runs"]

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        try:
            return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


async def resume_pending_runs() -> int:
    """On main.py startup, resume runs interrupted by restart or auto-resume
    those whose rate-limit pause window has expired (T-2-013, Sprint 2).

    Returns the count of runs scheduled for resume.

    Strategy:
    - status='running' → was active when service died → resume immediately.
    - status='paused_rate_limit' AND resume_after <= now → window expired,
      auto-resume.
    - status='paused_rate_limit' AND resume_after > now → leave for the
      periodic queue runner (Sprint 3) to pick up later.
    - Other statuses (pending/awaiting_approval/done/failed/aborted) → ignore.

    Each resume runs as a separate background task so this function returns
    quickly and main.py can continue starting other components.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, status, resume_after
              FROM pipeline_runs
             WHERE status IN ('running', 'paused_rate_limit')
             ORDER BY id
            """
        )
        rows = await cur.fetchall()

    if not rows:
        logger.info("resume_pending_runs: no runs to resume")
        return 0

    now = datetime.now()
    resumed = 0
    for row in rows:
        run_id = int(row["id"])
        status = row["status"]
        if status == "running":
            asyncio.create_task(_resume_one(run_id, reason="interrupted-by-restart"))
            resumed += 1
        elif status == "paused_rate_limit":
            ra = _parse_dt(row["resume_after"])
            if ra is None or ra <= now:
                asyncio.create_task(_resume_one(run_id, reason="rate-limit-window-expired"))
                resumed += 1
            else:
                logger.info(
                    "resume_pending_runs: run %s still paused until %s — skipping",
                    run_id, ra,
                )

    logger.info("resume_pending_runs: scheduled %d run(s) for background resume", resumed)
    return resumed


async def _resume_one(run_id: int, reason: str) -> None:
    """Background coroutine that calls PipelineRunner(run_id).resume().

    Catches all exceptions so a single bad run doesn't crash the event loop.
    """
    logger.info("resume_pending_runs: resuming run %s (%s)", run_id, reason)
    try:
        await PipelineRunner(run_id).resume()
    except Exception:  # noqa: BLE001 — already handled inside runner; this is paranoia
        logger.exception("resume_pending_runs: resume of run %s crashed", run_id)
