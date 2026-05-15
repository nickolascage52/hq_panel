"""GitManager — git operations for a pipeline workspace (T-3-002, Sprint 3).

Wraps GitPython for the common ops: init, branches, commits, push, worktrees,
status/diff. All file I/O goes through asyncio.to_thread so we don't block
the event loop.

Design choice (per docs/dependency-decisions.md): GitPython > raw subprocess.
Pros: typed Refs, structured errors, less escaping. Cons: heavier import,
holds Windows file handles longer (mitigated in PipelineWorkspace cleanup).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import git  # GitPython, T-2-002a

from .exceptions import GitError

logger = logging.getLogger(__name__)


class GitManager:
    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace_path = Path(workspace_path)

    # ── Repo open helper ─────────────────────────────────────────────────

    def _repo(self) -> git.Repo:
        try:
            return git.Repo(self.workspace_path)
        except git.InvalidGitRepositoryError as e:
            raise GitError(f"not a git repo: {self.workspace_path}", command="open") from e
        except git.NoSuchPathError as e:
            raise GitError(f"path does not exist: {self.workspace_path}", command="open") from e

    # ── Public ops ───────────────────────────────────────────────────────

    async def init_repo(self, initial_commit: bool = True) -> None:
        """Init a new repo at workspace_path. Idempotent: skips if .git already exists."""
        await asyncio.to_thread(self._init_repo_sync, initial_commit)

    def _init_repo_sync(self, initial_commit: bool) -> None:
        if (self.workspace_path / ".git").exists():
            logger.info("GitManager: %s already initialized", self.workspace_path)
            return
        repo = git.Repo.init(self.workspace_path)
        try:
            with repo.config_writer() as cw:
                cw.set_value("user", "name", "AI Pipeline")
                cw.set_value("user", "email", "pipeline@ai-delivery.local")
            if initial_commit:
                # Allow empty commit so HEAD exists for branch creation.
                repo.index.commit("Initial empty commit", skip_hooks=True)
                logger.info("GitManager: initialized %s with empty initial commit",
                            self.workspace_path)
        finally:
            repo.close()

    async def create_branch(self, name: str, base: str | None = None) -> None:
        """Create branch `name` (optionally from `base`) and switch to it."""
        await asyncio.to_thread(self._create_branch_sync, name, base)

    def _create_branch_sync(self, name: str, base: str | None) -> None:
        repo = self._repo()
        try:
            if base:
                new = repo.create_head(name, base)
            else:
                new = repo.create_head(name)
            new.checkout()
            logger.info("GitManager: branch '%s' created (base=%s)", name, base or "HEAD")
        except git.GitCommandError as e:
            raise GitError(str(e), command=f"create_branch {name}") from e
        finally:
            repo.close()

    async def commit_all(self, message: str) -> str | None:
        """`git add -A && git commit -m`. Returns commit SHA, or None if nothing to commit."""
        return await asyncio.to_thread(self._commit_all_sync, message)

    def _commit_all_sync(self, message: str) -> str | None:
        repo = self._repo()
        try:
            repo.git.add(A=True)
            if not repo.is_dirty(untracked_files=True) and not repo.index.diff("HEAD"):
                logger.info("GitManager: commit_all — nothing to commit")
                return None
            commit = repo.index.commit(message, skip_hooks=True)
            sha = commit.hexsha[:12]
            logger.info("GitManager: committed %s — %s", sha, message[:60])
            return sha
        except git.GitCommandError as e:
            raise GitError(str(e), command="commit_all") from e
        finally:
            repo.close()

    async def push(self, remote: str = "origin", branch: str | None = None) -> None:
        """Push branch (default current) to remote. Raises GitError on failure."""
        await asyncio.to_thread(self._push_sync, remote, branch)

    def _push_sync(self, remote: str, branch: str | None) -> None:
        repo = self._repo()
        try:
            ref = branch or repo.active_branch.name
            try:
                repo.remote(remote)
            except ValueError as e:
                raise GitError(f"remote '{remote}' not configured", command="push") from e
            info = repo.git.push(remote, ref, set_upstream=True)
            logger.info("GitManager: pushed %s/%s — %s", remote, ref, info)
        except git.GitCommandError as e:
            raise GitError(str(e), command=f"push {remote} {branch}") from e
        finally:
            repo.close()

    async def create_worktree(self, branch_name: str, path: str | Path) -> Path:
        """Create a git worktree at `path` for `branch_name` (creates branch if missing)."""
        return await asyncio.to_thread(self._create_worktree_sync, branch_name, Path(path))

    def _create_worktree_sync(self, branch_name: str, path: Path) -> Path:
        repo = self._repo()
        try:
            path = path.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Ensure branch exists
            if branch_name not in [h.name for h in repo.heads]:
                repo.create_head(branch_name)
            repo.git.worktree("add", str(path), branch_name)
            logger.info("GitManager: worktree %s -> %s", branch_name, path)
            return path
        except git.GitCommandError as e:
            raise GitError(str(e), command=f"worktree add {branch_name}") from e
        finally:
            repo.close()

    async def merge_worktrees(
        self,
        target_branch: str,
        source_branches: list[str],
    ) -> list[str]:
        """Merge each source branch into target. Returns list of merged commit SHAs."""
        return await asyncio.to_thread(
            self._merge_worktrees_sync, target_branch, source_branches,
        )

    def _merge_worktrees_sync(
        self, target_branch: str, source_branches: list[str],
    ) -> list[str]:
        repo = self._repo()
        merged: list[str] = []
        try:
            repo.git.checkout(target_branch)
            for src in source_branches:
                try:
                    out = repo.git.merge(src, no_ff=True, m=f"Merge {src} into {target_branch}")
                    merged.append(repo.head.commit.hexsha[:12])
                    logger.info("GitManager: merged %s into %s — %s", src, target_branch, out[:80])
                except git.GitCommandError as e:
                    # Don't auto-resolve — surface for human review.
                    raise GitError(
                        f"merge conflict {src} -> {target_branch}: {e}",
                        command=f"merge {src}",
                    ) from e
        finally:
            repo.close()
        return merged

    async def get_status(self) -> str:
        return await asyncio.to_thread(self._get_status_sync)

    def _get_status_sync(self) -> str:
        repo = self._repo()
        try:
            return repo.git.status("--porcelain")
        finally:
            repo.close()

    async def get_diff(self, against: str = "main") -> str:
        return await asyncio.to_thread(self._get_diff_sync, against)

    def _get_diff_sync(self, against: str) -> str:
        repo = self._repo()
        try:
            return repo.git.diff(against, "HEAD")
        except git.GitCommandError as e:
            raise GitError(str(e), command=f"diff {against}") from e
        finally:
            repo.close()
