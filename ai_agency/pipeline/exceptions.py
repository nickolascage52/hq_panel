"""Pipeline-specific exception hierarchy.

All exceptions raised by pipeline modules inherit from PipelineError so
the runner can catch and handle them uniformly.
"""


class PipelineError(Exception):
    """Base for all pipeline errors. Implemented in T-2-006."""


class RateLimitExceeded(PipelineError):
    """Implemented in T-2-006."""


class WorkspaceError(PipelineError):
    """Implemented in T-2-006."""


class PhaseExecutionError(PipelineError):
    """Implemented in T-2-006."""


class ApprovalRequired(PipelineError):
    """Implemented in T-2-006."""


class ClaudeCodeError(PipelineError):
    """Implemented in T-2-006."""


class GitError(PipelineError):
    """Implemented in T-2-006."""
