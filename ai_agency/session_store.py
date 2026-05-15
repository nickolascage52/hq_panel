"""
HQ session store backed by `hq_sessions` table (T-1-012, Sprint 1).

Replaces the previous in-memory `_sessions: dict` that lived in `hq_v3_api.py`.
Sessions now survive service restarts.

Public contract (used by api.py):
- create_session(user_id, role, name, ip, user_agent) -> dict
- get_session(token) -> dict | None     # auto-removes expired sessions
- delete_session(token) -> None
- cleanup_expired_sessions() -> int     # called periodically by scheduler

Returned session dict shape (kept identical to the legacy in-memory format
so that api.py call sites do not need to change):

    {
        "token": str,
        "user_id": int,
        "role": str,
        "name": str,
        "expires": datetime,         # alias of expires_at, kept for legacy
        "expires_at": datetime,
        "created_at": datetime,
        "last_activity_at": datetime,
    }
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

import aiosqlite

from database import DB_PATH

logger = logging.getLogger("session_store")

SESSION_TTL_DAYS = 7


def _row_to_session(row: aiosqlite.Row, name: str) -> dict[str, Any]:
    """Convert a hq_sessions JOIN hq_users row into the legacy session dict."""

    expires_at = _parse_dt(row["expires_at"])
    return {
        "token": row["token"],
        "user_id": int(row["user_id"]),
        "role": row["role"],
        "name": name,
        "expires": expires_at,
        "expires_at": expires_at,
        "created_at": _parse_dt(row["created_at"]),
        "last_activity_at": _parse_dt(row["last_activity_at"]),
    }


def _parse_dt(value: Any) -> datetime:
    """SQLite returns TIMESTAMP as ISO string with seconds. Be lenient."""

    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.now()
    text = str(value)
    # SQLite default CURRENT_TIMESTAMP gives 'YYYY-MM-DD HH:MM:SS'.
    # datetime.fromisoformat handles both 'T' and ' ' since Python 3.11.
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        # Fallback: ignore microseconds/timezones issues.
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")


async def create_session(
    user_id: int,
    role: str,
    name: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Create a fresh session row, return the session dict (legacy shape)."""

    token = secrets.token_hex(32)
    now = datetime.now()
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """
            INSERT INTO hq_sessions (token, user_id, role, expires_at, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, user_id, role, expires_at.isoformat(sep=" ", timespec="seconds"),
             ip_address, user_agent),
        )
        await db.commit()

    logger.info("hq_sessions: created session for user_id=%s role=%s", user_id, role)

    return {
        "token": token,
        "user_id": user_id,
        "role": role,
        "name": name,
        "expires": expires_at,
        "expires_at": expires_at,
        "created_at": now,
        "last_activity_at": now,
    }


async def get_session(token: str) -> dict[str, Any] | None:
    """Return active session for a token, or None.

    Auto-deletes expired sessions to keep the table clean (best-effort).
    Updates last_activity_at on hit (sliding TTL is NOT implemented — TTL is
    fixed from create_session; we only track activity for audit purposes).
    """

    if not token:
        return None

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT s.token, s.user_id, s.role, s.created_at, s.expires_at,
                   s.last_activity_at, COALESCE(u.name, 'Unknown') AS user_name
              FROM hq_sessions s
              LEFT JOIN hq_users u ON u.id = s.user_id
             WHERE s.token = ?
             LIMIT 1
            """,
            (token,),
        )
        row = await cur.fetchone()

        if row is None:
            return None

        expires_at = _parse_dt(row["expires_at"])
        if expires_at < datetime.now():
            # Expired — delete and return None.
            await db.execute("DELETE FROM hq_sessions WHERE token = ?", (token,))
            await db.commit()
            return None

        # Touch last_activity_at (best-effort; doesn't change TTL).
        await db.execute(
            "UPDATE hq_sessions SET last_activity_at = CURRENT_TIMESTAMP WHERE token = ?",
            (token,),
        )
        await db.commit()

    return _row_to_session(row, name=row["user_name"])


async def delete_session(token: str) -> None:
    """Delete a session by token (logout). Idempotent."""

    if not token:
        return

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("DELETE FROM hq_sessions WHERE token = ?", (token,))
        await db.commit()


async def cleanup_expired_sessions() -> int:
    """Delete all expired sessions. Returns count. Called periodically."""

    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "DELETE FROM hq_sessions WHERE expires_at < CURRENT_TIMESTAMP"
        )
        deleted = cur.rowcount or 0
        await db.commit()

    if deleted:
        logger.info("hq_sessions: cleaned up %d expired sessions", deleted)
    return deleted
