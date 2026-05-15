"""AI Pipeline module — autonomous client project development.

Public exports:
    PipelineRunner   — main coordinator for one pipeline-run
    resume_pending_runs(db) — called from main.py on startup to resume
                              runs that were running/paused before restart
"""
from .runner import PipelineRunner

__all__ = ['PipelineRunner', 'resume_pending_runs']


async def resume_pending_runs(db):
    """On main.py startup, resume runs interrupted by restart or auto-resume
    those whose rate-limit pause window has expired.

    Implemented in T-2-013.
    """
    raise NotImplementedError('Implemented in T-2-013')
