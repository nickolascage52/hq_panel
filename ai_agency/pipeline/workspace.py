"""PipelineWorkspace — manages /pipeline_workspaces/<run_id>/ directory.

Responsibilities:
- Create directory + git init + copy .claude/agents templates
- Track docs/, src/, etc.
- cleanup() on abort
"""
import logging
logger = logging.getLogger(__name__)


class PipelineWorkspace:
    """Implemented in T-2-007."""

    def __init__(self, run_id: int):
        self.run_id = run_id

    @property
    def path(self):
        raise NotImplementedError('Implemented in T-2-007')

    async def create(self):
        raise NotImplementedError('Implemented in T-2-007')

    def exists(self) -> bool:
        raise NotImplementedError('Implemented in T-2-007')

    async def cleanup(self):
        raise NotImplementedError('Implemented in T-2-007')
