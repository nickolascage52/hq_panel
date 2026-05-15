"""PipelineProgress — emit events to pipeline_events + WebSocket subscribers (T-2-008).

Pattern mirrors orchestrator.TaskProgress (existing, untouchable until Sprint 5).
Each PipelineRunner has one instance that writes events to DB and broadcasts
to subscribed websockets in real time.

Threading model: WebSocket subscribers are stored in a process-global dict
keyed by run_id. emit_event writes to DB synchronously (await), then sends
to each subscriber concurrently via asyncio.gather. Failed sends drop the
subscriber.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

# Process-global: {run_id: [WebSocket, ...]}
_subscribers: dict[int, list[Any]] = {}


class PipelineProgress:
    """Event emitter for one pipeline-run."""

    def __init__(self, run_id: int, db: Any | None = None) -> None:
        """db kept for legacy parity with TaskProgress; we open our own connection
        per emit because aiosqlite connections aren't safe to share across tasks."""
        self.run_id = run_id

    async def emit_event(
        self,
        event_type: str,
        payload: dict | None = None,
        sprint_id: int | None = None,
        delivery_task_id: int | None = None,
        severity: str = "info",
    ) -> int:
        """Persist event in pipeline_events + broadcast to subscribers.

        Returns the new event id.
        """
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        created_at = datetime.now()

        async with aiosqlite.connect(str(DB_PATH)) as db:
            cur = await db.execute(
                """
                INSERT INTO pipeline_events
                    (run_id, sprint_id, delivery_task_id, event_type, severity, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (self.run_id, sprint_id, delivery_task_id, event_type, severity, payload_json),
            )
            event_id = cur.lastrowid
            await db.commit()

        # Broadcast (best-effort, doesn't block on failures)
        await self._broadcast({
            "id": event_id,
            "run_id": self.run_id,
            "sprint_id": sprint_id,
            "delivery_task_id": delivery_task_id,
            "event_type": event_type,
            "severity": severity,
            "payload": payload or {},
            "created_at": created_at.isoformat(sep=" ", timespec="seconds"),
        })

        return event_id  # type: ignore[return-value]

    async def _broadcast(self, message: dict) -> None:
        subscribers = list(_subscribers.get(self.run_id, ()))
        if not subscribers:
            return

        async def _send(ws: Any) -> Any:
            try:
                await ws.send_json(message)
                return None
            except Exception as e:  # noqa: BLE001 — broad: any send failure drops the sub
                return (ws, e)

        results = await asyncio.gather(*(_send(ws) for ws in subscribers))
        # Drop failed subscribers
        for failure in results:
            if failure is not None:
                ws, err = failure
                logger.info(
                    "PipelineProgress: dropping subscriber on run %s (send failed: %s)",
                    self.run_id, err,
                )
                PipelineProgress.unsubscribe(self.run_id, ws)

    # ── Class-level subscriber registry ────────────────────────────────

    @staticmethod
    def subscribe(run_id: int, websocket: Any) -> None:
        """Register a WebSocket to receive events for run_id.
        Called from /ws/pipeline/{run_id} handler after accept().
        """
        _subscribers.setdefault(run_id, []).append(websocket)
        logger.debug(
            "PipelineProgress: +1 subscriber for run %s (total %d)",
            run_id, len(_subscribers[run_id]),
        )

    @staticmethod
    def unsubscribe(run_id: int, websocket: Any) -> None:
        """Remove a WebSocket subscription. Idempotent."""
        if run_id not in _subscribers:
            return
        try:
            _subscribers[run_id].remove(websocket)
        except ValueError:
            return
        if not _subscribers[run_id]:
            del _subscribers[run_id]

    @staticmethod
    def subscriber_count(run_id: int) -> int:
        """Diagnostic helper."""
        return len(_subscribers.get(run_id, ()))
