"""PhaseBase — abstract base class for all pipeline phases (T-2-010).

Concrete phases override `_run()` only. The base class wraps that with:
- emit_event('phase_started', ...) before
- emit_event('phase_completed', ...) after success
- emit_event('phase_failed', ..., severity='error') + re-raise on failure

Subclasses MUST set `name` (matches pipeline_runs.current_phase values:
'prompt' | 'prd' | 'architecture' | 'sprints' | 'execution' | 'validation' | 'handoff').
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runner import PipelineRunner

logger = logging.getLogger(__name__)


class PhaseBase(ABC):
    name: str = "base"

    def __init__(self, runner: "PipelineRunner") -> None:
        self.runner = runner

    async def execute(self) -> None:
        """Lifecycle: started → _run → completed (or failed + re-raise)."""
        await self.runner.progress.emit_event(
            "phase_started",
            payload={"phase": self.name},
        )
        logger.info("Pipeline %s: phase '%s' started", self.runner.run_id, self.name)
        try:
            await self._run()
        except Exception as e:  # noqa: BLE001 — emit then re-raise for runner to handle
            await self.runner.progress.emit_event(
                "phase_failed",
                payload={"phase": self.name, "error": str(e), "type": type(e).__name__},
                severity="error",
            )
            logger.exception("Pipeline %s: phase '%s' failed", self.runner.run_id, self.name)
            raise

        await self.runner.progress.emit_event(
            "phase_completed",
            payload={"phase": self.name},
        )
        logger.info("Pipeline %s: phase '%s' completed", self.runner.run_id, self.name)

    @abstractmethod
    async def _run(self) -> None:
        """Subclass implements the actual phase work here.

        For T-2-010 stubs: just `await asyncio.sleep(2)` to simulate work.
        Real work is wired in Sprint 3 (T-3-XXX).
        """
        raise NotImplementedError
