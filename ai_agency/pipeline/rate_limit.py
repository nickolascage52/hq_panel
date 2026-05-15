"""RateLimitManager — track Claude usage + downgrade chain (T-4-001, Sprint 4).

Sprint 4 stub: persists state in pipeline_rate_limits but doesn't yet parse
'claude /usage' (which requires Claude Code CLI on host). Provides full
downgrade chain logic for Phase 5 to consult.

Real /usage parsing — wire in when Claude CLI is installed on prod
(deferred backlog v1.1).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

# Downgrade chain per task type. select_model_for_task picks the highest
# model under threshold; if all over budget, returns None -> caller pauses.
DOWNGRADE_CHAINS: dict[str, list[str]] = {
    'architecture':   ['opus', 'sonnet'],
    'planning':       ['opus', 'sonnet'],
    'building':       ['sonnet', 'haiku'],
    'validation':     ['haiku'],
    'review':         ['sonnet', 'haiku'],
    'prd_check':      ['opus', 'sonnet'],
}

WEEKLY_DOWNGRADE_THRESHOLD = 70  # %, beyond which downgrade kicks in
WEEKLY_PAUSE_THRESHOLD = 90      # %, beyond which we pause entirely


class RateLimitManager:
    def __init__(self, db=None):
        # db kept for API compatibility — we open per-call connections
        pass

    async def get_state(self) -> dict[str, dict]:
        """Return {model: {weekly_used, weekly_limit, pct, reset_at}}."""
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM pipeline_rate_limits ORDER BY model')
            rows = await cur.fetchall()
        state = {}
        for row in rows:
            limit = row['tokens_limit_weekly']
            used = row['tokens_used_weekly'] or 0
            pct = (used / limit * 100) if limit else 0
            state[row['model']] = {
                'weekly_used': used,
                'weekly_limit': limit,
                'pct': pct,
                'reset_at': row['weekly_reset_at'],
                'last_updated': row['last_updated'],
            }
        return state

    async def select_model_for_task(self, task_type: str) -> str | None:
        """Best available model for task_type, None if all are over WEEKLY_PAUSE_THRESHOLD."""
        state = await self.get_state()
        chain = DOWNGRADE_CHAINS.get(task_type, ['sonnet', 'haiku'])
        for model in chain:
            s = state.get(model)
            if s and s['pct'] < WEEKLY_DOWNGRADE_THRESHOLD:
                return model
        for model in chain:
            s = state.get(model)
            if s and s['pct'] < WEEKLY_PAUSE_THRESHOLD:
                logger.warning('select_model: forced %s at %.1f%% (over downgrade threshold)',
                               model, s['pct'])
                return model
        return None

    async def should_pause(self) -> bool:
        """True if all models are over WEEKLY_PAUSE_THRESHOLD."""
        state = await self.get_state()
        if not state:
            return False
        return all(s['pct'] >= WEEKLY_PAUSE_THRESHOLD for s in state.values())

    async def get_resume_estimate(self) -> datetime | None:
        """Earliest weekly_reset_at among all models — when pause may auto-lift."""
        state = await self.get_state()
        resets = [s['reset_at'] for s in state.values() if s['reset_at']]
        if not resets:
            return datetime.now() + timedelta(days=7)
        parsed = []
        for r in resets:
            try:
                parsed.append(datetime.fromisoformat(str(r)))
            except ValueError:
                pass
        return min(parsed) if parsed else None

    async def record_usage(self, model: str, tokens_in: int, tokens_out: int) -> None:
        """Increment counters. Called by ClaudeRunner after each successful call."""
        total = (tokens_in or 0) + (tokens_out or 0)
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                """
                UPDATE pipeline_rate_limits
                   SET tokens_used_weekly = COALESCE(tokens_used_weekly, 0) + ?,
                       tokens_used_session = COALESCE(tokens_used_session, 0) + ?,
                       last_updated = CURRENT_TIMESTAMP
                 WHERE model = ?
                """,
                (total, total, model),
            )
            await db.commit()
