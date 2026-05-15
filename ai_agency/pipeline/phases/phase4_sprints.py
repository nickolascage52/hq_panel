"""Phase 4: break PRD into sprints + tasks.

Implemented in T-2-010 (skeleton) and Sprint 3 (real Claude integration).
"""
import asyncio
import logging
from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase4Sprints(PhaseBase):
    name = 'sprints'

    async def execute(self) -> None:
        raise NotImplementedError('Implemented in T-2-010')
