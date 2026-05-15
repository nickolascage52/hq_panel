"""Phase 3: select architecture + write ARCHITECTURE.md.

Implemented in T-2-010 (skeleton) and Sprint 3 (real Claude integration).
"""
import asyncio
import logging
from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase3Architecture(PhaseBase):
    name = 'architecture'

    async def execute(self) -> None:
        raise NotImplementedError('Implemented in T-2-010')
