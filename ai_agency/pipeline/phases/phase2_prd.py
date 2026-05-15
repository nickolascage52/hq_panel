"""Phase 2: generate PRD from production prompt.

Implemented in T-2-010 (skeleton) and Sprint 3 (real Claude integration).
"""
import asyncio
import logging
from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase2PRD(PhaseBase):
    name = 'prd'

    async def execute(self) -> None:
        raise NotImplementedError('Implemented in T-2-010')
