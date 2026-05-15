"""Pipeline audit log helper (v1.3).

Single function `log_action()` that any admin-action site (HTTP endpoint,
Telegram command, future API) can call to record who did what to which run.

Records go to pipeline_audit_log table (created by _migrate_pipeline_v1_3
in database.py).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)


async def log_action(
    *,
    run_id: int | None,
    action: str,
    actor: str,
    actor_id: int | None = None,
    source: str = "http",
    from_status: str | None = None,
    to_status: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an admin action in pipeline_audit_log.

    Args:
        run_id: which run was acted upon (None for global actions like 'create')
        action: short verb — 'create', 'pause', 'resume', 'abort', 'approve', etc.
        actor: human-readable identifier ('owner@hq', 'telegram_owner', 'system')
        actor_id: numeric ID (hq_users.id, telegram user_id) if applicable
        source: 'http' | 'telegram' | 'system' | 'cron'
        from_status / to_status: status transition (optional, for state changes)
        details: arbitrary JSON-serialisable dict (reason, IP, etc.)

    Best-effort: if logging fails, swallow exception (must never break the
    actual admin action being audited).
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                """
                INSERT INTO pipeline_audit_log
                    (run_id, action, actor, actor_id, source,
                     from_status, to_status, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    action,
                    actor,
                    actor_id,
                    source,
                    from_status,
                    to_status,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("audit log write failed for action=%s run=%s", action, run_id)


async def list_audit_log(
    *,
    run_id: int | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Read recent audit entries with optional filters."""
    where = []
    vals: list[Any] = []
    if run_id is not None:
        where.append("run_id = ?")
        vals.append(run_id)
    if action:
        where.append("action = ?")
        vals.append(action)
    sql = "SELECT * FROM pipeline_audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    vals.extend([limit, offset])

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, vals)
        rows = await cur.fetchall()

    out = []
    for row in rows:
        d = {k: row[k] for k in row.keys()}
        try:
            d["details"] = json.loads(d.pop("details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            d["details"] = {}
        out.append(d)
    return out
