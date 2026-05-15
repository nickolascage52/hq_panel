"""PipelineWorkspace — manages /pipeline_workspaces/<run_id>/ directory (T-2-007).

Each pipeline-run gets its own isolated directory with its own git repo.
Layout:
    pipeline_workspaces/<run_id>/
    ├── .git/                   # separate repo per run
    ├── CLAUDE.md               # project rules (placeholder until template copied)
    ├── docs/
    │   └── .gitkeep
    └── .claude/
        └── agents/             # populated from agency/standards/<type>/ in Sprint 3
            └── .gitkeep

Operations are async-friendly: file I/O wrapped in `asyncio.to_thread` so we
don't block the event loop. Git operations via GitPython.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import git  # GitPython, T-2-002a

from .exceptions import WorkspaceError

logger = logging.getLogger(__name__)

# Root for all pipeline workspaces. Resolves to ai_agency/pipeline_workspaces/
# both locally and on prod (since main.py runs from ai_agency/).
WORKSPACES_ROOT = Path(__file__).resolve().parent.parent / "pipeline_workspaces"


class PipelineWorkspace:
    """Filesystem + git layer for one pipeline-run."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    @property
    def path(self) -> Path:
        """Absolute path to this run's workspace directory."""
        return WORKSPACES_ROOT / str(self.run_id)

    @property
    def docs_path(self) -> Path:
        return self.path / "docs"

    @property
    def claude_agents_path(self) -> Path:
        return self.path / ".claude" / "agents"

    def exists(self) -> bool:
        """True if the workspace directory exists on disk."""
        return self.path.exists() and self.path.is_dir()

    async def create(self) -> None:
        """Create workspace directory + git init + scaffold files.

        Idempotent: if `.git` already exists, treats workspace as already
        created (no-op for git init, but ensures dirs/files are in place).

        Raises WorkspaceError on filesystem or git failure.
        """
        try:
            await asyncio.to_thread(self._create_sync)
        except Exception as e:
            logger.exception("Failed to create workspace for run %s", self.run_id)
            raise WorkspaceError(f"create() failed: {e}", path=str(self.path)) from e

    def _create_sync(self) -> None:
        """Synchronous body of create(); runs in worker thread."""
        # 1. Make root + run dir + standard subdirs.
        WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
        self.path.mkdir(parents=True, exist_ok=True)
        self.docs_path.mkdir(parents=True, exist_ok=True)
        self.claude_agents_path.mkdir(parents=True, exist_ok=True)

        # 2. .gitkeep files so empty dirs survive git operations.
        (self.docs_path / ".gitkeep").touch(exist_ok=True)
        (self.claude_agents_path / ".gitkeep").touch(exist_ok=True)

        # 3. Placeholder CLAUDE.md (real content generated in Phase 3).
        claude_md = self.path / "CLAUDE.md"
        if not claude_md.exists():
            claude_md.write_text(
                f"# Pipeline Run #{self.run_id}\n\n"
                "This file will be populated in Phase 3 (Architecture decision).\n",
                encoding="utf-8",
            )

        # 4. Git init (idempotent — checks if .git exists).
        git_dir = self.path / ".git"
        if not git_dir.exists():
            repo = git.Repo.init(self.path)
            # Initial commit with the scaffolded files (so branches have a base).
            repo.index.add([
                str(claude_md.relative_to(self.path)),
                str((self.docs_path / ".gitkeep").relative_to(self.path)),
                str((self.claude_agents_path / ".gitkeep").relative_to(self.path)),
            ])
            # Configure local user (avoid global git config dependency).
            with repo.config_writer() as cw:
                cw.set_value("user", "name", "AI Pipeline")
                cw.set_value("user", "email", "pipeline@ai-delivery.local")
            repo.index.commit(f"Initial workspace scaffold for pipeline-run {self.run_id}")
            logger.info("Workspace %s: git initialized + initial commit", self.run_id)
        else:
            logger.info("Workspace %s: .git exists, skipping init (idempotent)", self.run_id)

    async def cleanup(self) -> None:
        """Remove the workspace directory entirely (used by abort).

        Idempotent: returns silently if the directory doesn't exist.
        Raises WorkspaceError on filesystem failure.
        """
        if not self.exists():
            return
        try:
            await asyncio.to_thread(self._cleanup_sync)
        except Exception as e:
            logger.exception("Failed to cleanup workspace %s", self.run_id)
            raise WorkspaceError(f"cleanup() failed: {e}", path=str(self.path)) from e

    def _cleanup_sync(self) -> None:
        """Synchronous body of cleanup(); runs in worker thread."""
        # On Windows, .git/objects/pack files can have read-only attrs which break
        # shutil.rmtree. The onerror handler chmod+w-s them and retries.
        def _force_writable(func, path, exc_info):
            import os
            import stat
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                logger.warning("Could not remove %s during cleanup", path)

        shutil.rmtree(self.path, onerror=_force_writable)
        logger.info("Workspace %s: removed", self.run_id)
