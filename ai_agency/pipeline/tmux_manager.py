"""TmuxManager — tmux session control for pipeline-runs (T-3-003, Sprint 3).

Designed for Linux production. On Windows (no tmux), every operation logs a
warning and returns silently — local dev still works (we just lose the session
isolation feature). Sprint 3 phases tolerate `tmux not available` gracefully.

Uses asyncio.subprocess to call tmux. Requires tmux 3.x on PATH.
"""
from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


def tmux_available() -> bool:
    """True iff `tmux` binary is found on PATH."""
    return shutil.which("tmux") is not None


class TmuxManager:
    def __init__(self, run_id: int, sprint_number: int | None = None) -> None:
        self.run_id = run_id
        self.session_name = (
            f"pipeline-run-{run_id}" if sprint_number is None
            else f"pipeline-run-{run_id}-sprint-{sprint_number}"
        )

    @property
    def available(self) -> bool:
        return tmux_available()

    async def create(self, session_name: str | None = None) -> bool:
        """Create detached session. Returns True if created or already exists."""
        name = session_name or self.session_name
        if not self.available:
            logger.warning(
                "TmuxManager: tmux not available — skipping create %s "
                "(this is OK on Windows dev; required on prod Linux)",
                name,
            )
            return False
        if await self._exists(name):
            logger.info("TmuxManager: session %s already exists", name)
            return True
        rc, out, err = await _run("tmux", "new", "-d", "-s", name)
        if rc != 0:
            logger.warning("TmuxManager: create %s failed rc=%d: %s", name, rc, err)
            return False
        logger.info("TmuxManager: created session %s", name)
        return True

    async def exists(self) -> bool:
        return await self._exists(self.session_name)

    async def _exists(self, name: str) -> bool:
        if not self.available:
            return False
        rc, _, _ = await _run("tmux", "has-session", "-t", name)
        return rc == 0

    async def send_keys(self, text: str, enter: bool = True) -> bool:
        """Send keystrokes to the session's pane."""
        if not self.available:
            logger.warning("TmuxManager: tmux not available — skipping send_keys")
            return False
        args = ["tmux", "send-keys", "-t", self.session_name, text]
        if enter:
            args.extend(["Enter"])
        rc, _, err = await _run(*args)
        if rc != 0:
            logger.warning("TmuxManager: send_keys failed rc=%d: %s", rc, err)
            return False
        return True

    async def capture_pane(self) -> str:
        """Return current pane content (for log capture / debugging)."""
        if not self.available:
            return ""
        rc, out, _ = await _run("tmux", "capture-pane", "-t", self.session_name, "-p")
        return out if rc == 0 else ""

    async def kill(self) -> bool:
        """Terminate the session. Idempotent (no error if missing)."""
        if not self.available:
            return False
        rc, _, _ = await _run("tmux", "kill-session", "-t", self.session_name)
        if rc == 0:
            logger.info("TmuxManager: killed session %s", self.session_name)
            return True
        return False


# ── Subprocess helper ────────────────────────────────────────────────────


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr) — strings."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return proc.returncode or 0, out_b.decode(errors="replace"), err_b.decode(errors="replace")
