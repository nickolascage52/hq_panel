"""Pipeline queue: enforces 1 active run at a time (per ARCHITECTURE).

Implemented in Sprint 3 (T-3-XXX). Currently a stub.
"""
import logging
logger = logging.getLogger(__name__)


class PipelineQueue:
    @staticmethod
    async def enqueue(run_id: int, db):
        raise NotImplementedError('Implemented in Sprint 3')

    @staticmethod
    async def next_pending(db) -> int | None:
        raise NotImplementedError('Implemented in Sprint 3')
