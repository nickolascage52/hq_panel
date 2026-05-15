"""PhaseBase — abstract base class for all pipeline phases.

Implemented in T-2-010.
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PhaseBase(ABC):
    name: str = 'base'

    def __init__(self, runner):
        self.runner = runner

    @abstractmethod
    async def execute(self) -> None:
        """Run the phase. Should emit phase_started and phase_completed events."""
        raise NotImplementedError
