"""Git operations wrapper (init, branches, worktrees, commits, push).

Implemented in Sprint 3 (T-3-XXX). Currently a stub.
"""
import logging
logger = logging.getLogger(__name__)


class GitManager:
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path

    async def init(self):
        raise NotImplementedError('Implemented in Sprint 3')

    async def commit(self, message: str, files: list[str] | None = None):
        raise NotImplementedError('Implemented in Sprint 3')

    async def push(self, branch: str):
        raise NotImplementedError('Implemented in Sprint 3')
