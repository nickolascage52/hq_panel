"""Phase 2: generate PRD from production prompt.

T-2-010 (Sprint 2): stub implementation — sleeps 2 seconds to simulate work.
PhaseBase emits phase_started/phase_completed events around _run().

Real implementation in Sprint 3 (T-3-XXX) will wire claude-agent-sdk calls.
"""
from __future__ import annotations

import asyncio
import logging

from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase2PRD(PhaseBase):
    name = 'prd'

    async def _run(self) -> None:
        # Sprint 2 stub: simulate phase work without real Claude calls.
        # Sprint 3 will replace this body with actual claude_runner.run_phase_agent(...) call.
        await asyncio.sleep(2)
