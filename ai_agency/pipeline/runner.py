"""PipelineRunner — main coordinator for one pipeline-run (T-2-009, Sprint 2).

One PipelineRunner instance handles the lifecycle of exactly one
pipeline_runs row. Created from POST /api/pipeline/runs (via asyncio.create_task)
and resumed on service restart (via resume_pending_runs in T-2-013).

Lifecycle:
    pending → running → (one of)
        - done                   (all 7 phases ok)
        - paused_rate_limit      (RateLimitExceeded, will auto-resume after window)
        - awaiting_approval      (ApprovalRequired, waits for /approve)
        - failed                 (PhaseExecutionError or unexpected exception)

Sprint 2 stub: phases just sleep 2s. Sprint 3 wires real claude-agent-sdk calls.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiosqlite

from database import DB_PATH

from .exceptions import (
    PipelineError,
    RateLimitExceeded,
    ApprovalRequired,
    PhaseExecutionError,
)
from .progress import PipelineProgress
from .workspace import PipelineWorkspace

# Phase imports here (not at module top of phases/) — keeps circular-import risk down.
from .phases.base import PhaseBase
from .phases.phase1_prompt import Phase1Prompt
from .phases.phase2_prd import Phase2PRD
from .phases.phase3_architecture import Phase3Architecture
from .phases.phase4_sprints import Phase4Sprints
from .phases.phase5_execution import Phase5Execution
from .phases.phase6_validation import Phase6Validation
from .phases.phase7_handoff import Phase7Handoff

logger = logging.getLogger(__name__)

# Canonical phase order. Each entry's `.name` matches pipeline_runs.current_phase.
PHASES_ORDER: list[type[PhaseBase]] = [
    Phase1Prompt,
    Phase2PRD,
    Phase3Architecture,
    Phase4Sprints,
    Phase5Execution,
    Phase6Validation,
    Phase7Handoff,
]
PHASE_NAMES: list[str] = [c.name for c in PHASES_ORDER]


class PipelineRunner:
    """Coordinator for one pipeline_runs row."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.workspace = PipelineWorkspace(run_id)
        self.progress = PipelineProgress(run_id)

    # ── Public API ───────────────────────────────────────────────────────

    async def execute(self) -> None:
        """First-time execution: load run, init workspace, run all phases from start."""
        run = await self._load_run_or_fail()
        if run["status"] in ("done", "failed", "aborted"):
            logger.warning(
                "PipelineRunner %s: refusing to execute terminal status=%s",
                self.run_id, run["status"],
            )
            return

        await self._update_status("running", started_at=datetime.now())
        await self.progress.emit_event(
            "run_started",
            payload={"title": run["title"], "project_type": run["project_type"]},
        )

        try:
            await self.workspace.create()
        except Exception as e:  # noqa: BLE001 — workspace failure is fatal for this run
            await self._mark_failed(f"workspace.create() failed: {e}")
            return

        await self._run_phases(start_index=0)

    async def resume(self) -> None:
        """Resume a run that was interrupted (rate-limit pause expired or service restart)."""
        run = await self._load_run_or_fail()
        if run["status"] in ("done", "failed", "aborted"):
            logger.info("PipelineRunner %s: resume() called on terminal status=%s, no-op",
                        self.run_id, run["status"])
            return

        await self.progress.emit_event("resumed", payload={"from_status": run["status"]})
        await self._update_status("running")

        # Workspace might have been removed (abort) or never created — ensure it exists.
        if not self.workspace.exists():
            await self.workspace.create()

        # Determine where to pick up: re-run the phase recorded in current_phase
        # (it may have been mid-flight when interrupted).
        cur = run["current_phase"]
        if cur and cur in PHASE_NAMES:
            start_index = PHASE_NAMES.index(cur)
        else:
            start_index = 0
        logger.info("PipelineRunner %s: resuming from phase index %d (%s)",
                    self.run_id, start_index, PHASE_NAMES[start_index])

        await self._run_phases(start_index=start_index)

    # ── Internal ─────────────────────────────────────────────────────────

    async def _run_phases(self, start_index: int) -> None:
        try:
            for phase_cls in PHASES_ORDER[start_index:]:
                await self._set_current_phase(phase_cls.name)
                phase = phase_cls(self)
                await phase.execute()
            # All phases completed.
            await self._update_status(
                "done",
                completed_at=datetime.now(),
                current_phase=PHASE_NAMES[-1],
            )
            await self.progress.emit_event("run_completed", payload={"status": "done"})
            logger.info("PipelineRunner %s: all phases done", self.run_id)

        except RateLimitExceeded as e:
            await self._update_status(
                "paused_rate_limit",
                paused_at=datetime.now(),
                pause_reason=str(e) or "rate limit exceeded",
                resume_after=e.resume_after,
            )
            await self.progress.emit_event(
                "paused",
                payload={
                    "reason": "rate_limit",
                    "model": e.model,
                    "resume_after": e.resume_after.isoformat(sep=" ", timespec="seconds")
                    if e.resume_after else None,
                },
                severity="warning",
            )
            logger.info("PipelineRunner %s: paused for rate limit (model=%s, resume_after=%s)",
                        self.run_id, e.model, e.resume_after)

        except ApprovalRequired as e:
            await self._update_status(
                "awaiting_approval",
                paused_at=datetime.now(),
                pause_reason=str(e) or "awaiting approval",
            )
            await self.progress.emit_event(
                "approval_needed",
                payload={"phase": e.phase_name},
                severity="warning",
            )
            logger.info("PipelineRunner %s: paused awaiting approval (phase=%s)",
                        self.run_id, e.phase_name)

        except PhaseExecutionError as e:
            await self._mark_failed(f"phase '{e.phase_name}' failed: {e}")

        except PipelineError as e:
            await self._mark_failed(f"pipeline error: {e}")

        except Exception as e:  # noqa: BLE001 — unexpected: mark failed, log, swallow (long task)
            logger.exception("PipelineRunner %s: unexpected error", self.run_id)
            await self._mark_failed(f"unexpected: {type(e).__name__}: {e}")

    async def _load_run_or_fail(self) -> dict[str, Any]:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM pipeline_runs WHERE id = ?", (self.run_id,)
            )
            row = await cur.fetchone()
            if row is None:
                raise PipelineError(f"pipeline_runs id={self.run_id} not found")
            return dict(row)

    async def _update_status(self, status: str, **fields: Any) -> None:
        """Update pipeline_runs row. `fields` may include datetime values; converted to ISO."""
        sets = ["status = ?"]
        vals: list[Any] = [status]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            if isinstance(value, datetime):
                vals.append(value.isoformat(sep=" ", timespec="seconds"))
            else:
                vals.append(value)
        vals.append(self.run_id)
        sql = f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(sql, vals)
            await db.commit()

    async def _set_current_phase(self, phase_name: str) -> None:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                "UPDATE pipeline_runs SET current_phase = ? WHERE id = ?",
                (phase_name, self.run_id),
            )
            await db.commit()

    async def _mark_failed(self, error_message: str) -> None:
        await self._update_status(
            "failed",
            completed_at=datetime.now(),
            error_message=error_message,
        )
        await self.progress.emit_event(
            "run_failed",
            payload={"error": error_message},
            severity="error",
        )
        logger.error("PipelineRunner %s: marked failed — %s", self.run_id, error_message)
