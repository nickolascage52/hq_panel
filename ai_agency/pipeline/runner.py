"""PipelineRunner — main coordinator for one pipeline-run.

One PipelineRunner instance handles the lifecycle of exactly one
pipeline_runs row. Created on POST /api/pipeline/runs and resumed on
service restart.

Responsibilities:
- Iterate through Phase 1..7
- Handle pause/resume/abort
- Coordinate with PipelineWorkspace, PipelineProgress, RateLimitManager
"""
import logging
logger = logging.getLogger(__name__)


class PipelineRunner:
    """Implemented in T-2-009."""

    def __init__(self, run_id: int, db):
        self.run_id = run_id
        self.db = db

    async def execute(self):
        raise NotImplementedError('Implemented in T-2-009')

    async def resume(self):
        raise NotImplementedError('Implemented in T-2-009')
