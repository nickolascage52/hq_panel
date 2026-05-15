"""Pipeline-specific exception hierarchy (T-2-006, Sprint 2).

All exceptions raised by pipeline modules inherit from PipelineError so the
runner can catch and handle them uniformly. Each subclass carries
domain-specific attributes that the runner uses for routing (e.g.
RateLimitExceeded.resume_after tells when to auto-resume).
"""
from __future__ import annotations

from datetime import datetime


class PipelineError(Exception):
    """Base for all pipeline errors. Catch this in PipelineRunner.execute()."""


class RateLimitExceeded(PipelineError):
    """Raised when a Claude API call hits a hard rate limit and pipeline must pause.

    Attributes:
        resume_after: when the runner should auto-resume (UTC datetime).
        model: which model exhausted ('opus' | 'sonnet' | 'haiku' | 'all').
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        resume_after: datetime | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.resume_after = resume_after
        self.model = model


class WorkspaceError(PipelineError):
    """Raised when workspace creation, cleanup, or git init fails."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class PhaseExecutionError(PipelineError):
    """Raised when a phase fails irrecoverably.

    The runner marks the run as 'failed' and stores the message in
    pipeline_runs.error_message.
    """

    def __init__(self, message: str, phase_name: str | None = None) -> None:
        super().__init__(message)
        self.phase_name = phase_name


class ApprovalRequired(PipelineError):
    """Raised when autonomy_level requires owner approval before continuing.

    NOT a failure — the runner pauses and waits for POST /api/pipeline/runs/{id}/approve.
    """

    def __init__(self, message: str, phase_name: str | None = None) -> None:
        super().__init__(message)
        self.phase_name = phase_name


class ClaudeCodeError(PipelineError):
    """Raised when claude-agent-sdk call fails (other than rate limit)."""

    def __init__(self, message: str, agent_persona: str | None = None) -> None:
        super().__init__(message)
        self.agent_persona = agent_persona


class GitError(PipelineError):
    """Raised when a git operation fails (init/commit/push/worktree)."""

    def __init__(self, message: str, command: str | None = None) -> None:
        super().__init__(message)
        self.command = command
