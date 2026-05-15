"""Telegram pipeline notifier (T-4-010, Sprint 4).

Standalone watcher that subscribes to pipeline_events and sends owner
notifications for key events. Runs as a background task started in main.py.

Does NOT touch telegram_bot.py — that's untouchable until Sprint 5 per
project rules. Uses python-telegram-bot 21.x directly via a fresh Bot
client.

Events that trigger notifications:
- run_started
- approval_needed   (waits for owner action in HQ)
- paused            (rate limit or user)
- handoff_complete  (run finished — production_url if any)
- run_failed
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 5

NOTIFY_EVENTS = {
    "run_started":        ("🚀", "Pipeline #{run_id} стартовал"),
    "approval_needed":    ("🔔", "Pipeline #{run_id}: нужно одобрение ({phase})"),
    "approval_granted":   ("✅", "Pipeline #{run_id}: approval получен — продолжаю"),
    "paused":             ("⏸", "Pipeline #{run_id} на паузе ({reason})"),
    "rate_limit_hit":     ("🔋", "Pipeline #{run_id} упёрся в rate limit"),
    "handoff_complete":   ("🎉", "Pipeline #{run_id} готов к review"),
    "run_failed":         ("❌", "Pipeline #{run_id} сбойнул"),
    "run_completed":      ("✅", "Pipeline #{run_id} завершён"),
}


def _bot_available() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN")) and bool(os.getenv("TELEGRAM_OWNER_ID"))


async def _get_bot():
    """Lazy import + bot construction. Returns Bot or None if not configured."""
    if not _bot_available():
        return None
    try:
        from telegram import Bot  # type: ignore
    except ImportError:
        logger.warning("python-telegram-bot not installed — telegram notifications disabled")
        return None
    return Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])


async def send_pipeline_notification(run_id: int, event_type: str, payload: dict[str, Any]) -> None:
    """Best-effort notification send. Never raises."""
    bot = await _get_bot()
    if bot is None:
        return
    owner_id = os.getenv("TELEGRAM_OWNER_ID", "")
    if not owner_id:
        return

    icon, template = NOTIFY_EVENTS.get(event_type, ("📡", "Pipeline #{run_id}: " + event_type))
    fmt_args = {"run_id": run_id}
    fmt_args.update({k: str(v) for k, v in (payload or {}).items()})
    try:
        title = template.format(**{**fmt_args, **{"phase": fmt_args.get("phase", "—"),
                                                  "reason": fmt_args.get("reason", "—")}})
    except (KeyError, IndexError):
        title = template.format(run_id=run_id, phase="—", reason="—")

    body_lines = [f"{icon} {title}"]
    if payload.get("production_url"):
        body_lines.append(f"\n🔗 {payload['production_url']}")
    if payload.get("error"):
        body_lines.append(f"\n⚠️ {payload['error'][:300]}")

    text = "\n".join(body_lines)
    try:
        await bot.send_message(chat_id=int(owner_id), text=text)
        logger.info("Telegram notify sent: run=%s event=%s", run_id, event_type)
    except Exception as e:  # noqa: BLE001 — never break pipeline on notify failure
        logger.warning("Telegram notify failed for run=%s event=%s: %s", run_id, event_type, e)


async def watch_pipeline_events() -> None:
    """Long-running task — polls pipeline_events, dispatches notifications.

    Started as asyncio.create_task() from main.py. Tracks last seen event id
    in memory (loses position on restart — accepts a small chance of double
    notification for events emitted during the restart window).
    """
    if not _bot_available():
        logger.info("watch_pipeline_events: TELEGRAM_BOT_TOKEN/OWNER_ID missing — watcher disabled")
        return

    # Initialize cursor at current max event id (don't backfill historical events on first start).
    last_id = await _max_event_id()
    logger.info("watch_pipeline_events: started, polling every %ds, cursor=%d",
                WATCH_INTERVAL_SECONDS, last_id)

    while True:
        try:
            new_events = await _new_events_since(last_id)
            for ev in new_events:
                if ev["event_type"] in NOTIFY_EVENTS:
                    payload = {}
                    try:
                        import json
                        payload = json.loads(ev.get("payload_json") or "{}")
                    except (TypeError, ValueError):
                        pass
                    await send_pipeline_notification(ev["run_id"], ev["event_type"], payload)
                last_id = max(last_id, ev["id"])
        except Exception:  # noqa: BLE001
            logger.exception("watch_pipeline_events: poll cycle crashed")
        await asyncio.sleep(WATCH_INTERVAL_SECONDS)


async def _max_event_id() -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute("SELECT COALESCE(MAX(id), 0) FROM pipeline_events")
        (mx,) = await cur.fetchone() or (0,)
    return int(mx or 0)


async def _new_events_since(last_id: int) -> list[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, run_id, event_type, severity, payload_json, created_at
              FROM pipeline_events
             WHERE id > ?
             ORDER BY id ASC
             LIMIT 50
            """,
            (last_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
