"""ClaudeRunner — wrapper around claude-agent-sdk for spawning agent personas (T-3-001).

Each call streams events back to the caller (so PipelineProgress can record them
in real time) and persists the full execution row in the existing
`agent_executions` table for audit.

ANTHROPIC_API_KEY guard:
    If ANTHROPIC_API_KEY is missing or set to 'disabled-not-used' (Sprint 1 state),
    every call raises ClaudeCodeError with a clear message. This lets the runner
    surface a friendly failure instead of a cryptic SDK 401.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import AsyncIterator, Any

import aiosqlite

from database import DB_PATH

from .exceptions import ClaudeCodeError, RateLimitExceeded

logger = logging.getLogger(__name__)

# Claude Code SDK model name conventions. Tweak as Anthropic publishes new IDs.
MODEL_MAP = {
    "opus":   "claude-opus-4-5",
    "sonnet": "claude-sonnet-4-7",
    "haiku":  "claude-haiku-4-7",
}


def _api_key_available() -> bool:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    return bool(key) and key != "disabled-not-used" and not key.startswith("sk-ant-api03-REPLACE")


def _resolve_model(short: str) -> str:
    return MODEL_MAP.get(short, short)


class ClaudeRunner:
    """Stateless wrapper. One instance per pipeline-run is enough."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    async def run_agent(
        self,
        workspace_path: str,
        agent_persona: str,
        prompt: str,
        model: str = "opus",
        timeout: int = 1800,
        max_turns: int = 50,
    ) -> AsyncIterator[dict]:
        """Stream events from a Claude Code agent run.

        Yields normalized event dicts: {type, content, ...}.
        Logs the full execution to agent_executions on completion (success or fail).

        Raises:
            ClaudeCodeError: API key missing/disabled, or SDK error.
            RateLimitExceeded: hard rate limit hit (mapped from SDK error).
        """
        if not _api_key_available():
            raise ClaudeCodeError(
                "ANTHROPIC_API_KEY is missing or set to placeholder ('disabled-not-used'). "
                "Pipeline cannot make Claude calls until a real key is provisioned in .env. "
                "(Sprint 1 intentionally revoked the key — re-key in Sprint 3 prep.)",
                agent_persona=agent_persona,
            )

        # Lazy import — keeps module importable even if SDK install hiccups.
        try:
            from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions  # type: ignore
        except ImportError as e:
            raise ClaudeCodeError(
                f"claude-agent-sdk not installed: {e}",
                agent_persona=agent_persona,
            ) from e

        full_model = _resolve_model(model)
        logger.info(
            "ClaudeRunner: starting persona=%s model=%s cwd=%s (run_id=%s)",
            agent_persona, full_model, workspace_path, self.run_id,
        )

        execution_id = await self._begin_execution_log(agent_persona, model, prompt)
        started_at = datetime.now()
        output_chunks: list[str] = []
        tokens_used: int = 0
        success: bool = False
        error_text: str | None = None

        try:
            options = ClaudeAgentOptions(  # type: ignore[call-arg]
                cwd=workspace_path,
                model=full_model,
                # SDK API may also accept agents=[persona]; falls back to default if unsupported.
            )
            async with ClaudeSDKClient(options=options) as client:  # type: ignore[arg-type]
                # Apply timeout via wait_for around the iteration.
                async def _stream() -> AsyncIterator[dict]:
                    nonlocal tokens_used
                    async for event in client.query(prompt):  # type: ignore[attr-defined]
                        norm = _normalize_event(event)
                        if "tokens" in norm:
                            tokens_used += int(norm["tokens"] or 0)
                        if norm.get("text"):
                            output_chunks.append(str(norm["text"]))
                        yield norm

                async for ev in _wrap_timeout(_stream(), timeout):
                    yield ev
            success = True
        except RateLimitExceeded:
            raise
        except asyncio.TimeoutError:
            error_text = f"timeout after {timeout}s"
            raise ClaudeCodeError(error_text, agent_persona=agent_persona)
        except Exception as e:  # noqa: BLE001 — wrap and surface as ClaudeCodeError
            # SDK-specific rate limit detection (best effort)
            msg = str(e)
            if any(t in msg.lower() for t in ("rate limit", "429", "quota")):
                raise RateLimitExceeded(
                    f"rate limit during {agent_persona} run: {msg}",
                    model=model,
                ) from e
            error_text = msg
            raise ClaudeCodeError(msg, agent_persona=agent_persona) from e
        finally:
            await self._finish_execution_log(
                execution_id,
                output="\n".join(output_chunks),
                tokens=tokens_used,
                started_at=started_at,
                success=success,
                error=error_text,
            )

    # ── DB logging ───────────────────────────────────────────────────────

    async def _begin_execution_log(
        self, agent_name: str, model: str, prompt: str,
    ) -> int:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            cur = await db.execute(
                """
                INSERT INTO agent_executions
                    (task_id, agent_name, agent_role, parent_agent, input_brief, status)
                VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (None, agent_name, model, "pipeline_runner",
                 prompt[:8000]),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def _finish_execution_log(
        self,
        execution_id: int,
        output: str,
        tokens: int,
        started_at: datetime,
        success: bool,
        error: str | None,
    ) -> None:
        status = "done" if success else "failed"
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                """
                UPDATE agent_executions
                   SET output_text = ?, status = ?, tokens_used = ?, completed_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (output[:64000] if output else error, status, tokens, execution_id),
            )
            await db.commit()


# ── Helpers ──────────────────────────────────────────────────────────────


async def _wrap_timeout(gen: AsyncIterator[Any], timeout: int) -> AsyncIterator[Any]:
    """Yield from `gen` with an overall timeout. Raises asyncio.TimeoutError if exceeded."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"exceeded {timeout}s")
        try:
            ev = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield ev


def _normalize_event(raw: Any) -> dict:
    """Convert SDK-specific event objects into a plain dict.

    SDK API may return AssistantMessage, ToolUseBlock, etc. — we just extract
    the human-relevant fields to keep our event log uniform.
    """
    if isinstance(raw, dict):
        return raw
    text = ""
    tokens = 0
    type_name = type(raw).__name__
    # Try several known attrs without depending on a specific SDK version.
    for attr in ("text", "content", "message", "delta"):
        v = getattr(raw, attr, None)
        if isinstance(v, str) and v:
            text = v
            break
        if isinstance(v, list) and v and hasattr(v[0], "text"):
            text = "".join(getattr(b, "text", "") for b in v)
            break
    usage = getattr(raw, "usage", None)
    if usage is not None:
        tokens = int(getattr(usage, "input_tokens", 0)) + int(getattr(usage, "output_tokens", 0))
    return {"type": type_name, "text": text, "tokens": tokens}


# Module-level convenience for tests / phase code that doesn't need an instance.
async def run_phase_agent(
    workspace_path: str,
    agent_persona: str,
    task_md: str,
    model: str = "opus",
    timeout: int = 1800,
    run_id: int = 0,
) -> AsyncIterator[dict]:
    runner = ClaudeRunner(run_id)
    async for ev in runner.run_agent(workspace_path, agent_persona, task_md, model, timeout):
        yield ev
