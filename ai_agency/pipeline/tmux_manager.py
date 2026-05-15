"""Manages tmux sessions for pipeline-runs.

Implemented in Sprint 3 (T-3-XXX). Currently a stub.
"""
import logging
logger = logging.getLogger(__name__)


class TmuxManager:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.session_name = f'pipeline-run-{run_id}'

    async def create_session(self, session_name: str | None = None):
        raise NotImplementedError('Implemented in Sprint 3')

    async def kill_session(self):
        raise NotImplementedError('Implemented in Sprint 3')
