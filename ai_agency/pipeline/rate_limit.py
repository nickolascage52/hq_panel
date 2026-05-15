"""Rate limit tracking + downgrade logic for Claude API calls.

Implemented in Sprint 3 (T-3-XXX). Currently a stub.
"""
import logging
logger = logging.getLogger(__name__)


class RateLimitManager:
    def __init__(self, db):
        self.db = db

    async def select_model_for_task(self, task_type: str) -> str | None:
        raise NotImplementedError('Implemented in Sprint 3')

    async def maybe_pause_for_rate_limit(self, runner):
        raise NotImplementedError('Implemented in Sprint 3')
