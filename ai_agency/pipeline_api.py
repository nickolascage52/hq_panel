"""HQ Pipeline API — endpoints under /api/pipeline/* (T-2-011, Sprint 2).

Mounted from api.py via mount_pipeline_routes(app, require_role).

Sprint 2 endpoints (CRUD + events):
    POST   /api/pipeline/runs                           — create + spawn runner
    GET    /api/pipeline/runs                           — list, filtered
    GET    /api/pipeline/runs/{id}                      — details
    GET    /api/pipeline/runs/{id}/events               — event log, paged

WebSocket /ws/pipeline/{run_id} added in T-2-012.
Management endpoints (pause/resume/abort/approve) added in Sprint 3.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import aiosqlite
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from database import DB_PATH
from pipeline import PipelineRunner
from pipeline.progress import PipelineProgress
from session_store import get_session as _ss_get_session

logger = logging.getLogger("pipeline_api")


# ── Request bodies ───────────────────────────────────────────────────────


class PipelineRunCreateBody(BaseModel):
    title: str
    raw_idea: str
    project_type: str  # landing | telegram_bot | n8n | ai_assistant | custom
    autonomy_level: int = Field(default=2, ge=1, le=3)
    deploy_strategy: str = Field(default="none")  # none | vercel | aeza | custom
    delivery_project_id: int | None = None


# ── Helpers ──────────────────────────────────────────────────────────────


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


async def _spawn_runner(run_id: int) -> None:
    """Background coroutine that runs the full pipeline. Caught exceptions are
    already handled inside PipelineRunner._run_phases — this wrapper exists only
    to satisfy `asyncio.create_task(...)` signature.
    """
    try:
        await PipelineRunner(run_id).execute()
    except Exception:  # noqa: BLE001 — already logged by runner; don't crash event loop
        logger.exception("Pipeline runner background task crashed for run_id=%s", run_id)


async def _spawn_resume(run_id: int) -> None:
    """Background coroutine for /approve endpoint — calls runner.resume()."""
    try:
        await PipelineRunner(run_id).resume()
    except Exception:  # noqa: BLE001
        logger.exception("Pipeline resume background task crashed for run_id=%s", run_id)


# ── Route registration ───────────────────────────────────────────────────


def mount_pipeline_routes(
    app: FastAPI,
    require_role: Callable[..., Any],
) -> None:
    """Attach /api/pipeline/* endpoints to the existing FastAPI `app`.

    Called once from api.py after hq_v3 routes are mounted.
    """

    # ── POST /api/pipeline/runs ──────────────────────────────────────────

    @app.post("/api/pipeline/runs", status_code=201)
    async def pipeline_runs_create(
        payload: PipelineRunCreateBody,
        session: dict = Depends(require_role("owner")),
    ):
        """Create a new pipeline-run and spawn the runner in background."""
        async with aiosqlite.connect(str(DB_PATH)) as db:
            cur = await db.execute(
                """
                INSERT INTO pipeline_runs
                    (title, raw_idea, project_type, autonomy_level, deploy_strategy,
                     delivery_project_id, initiated_by, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    payload.title,
                    payload.raw_idea,
                    payload.project_type,
                    payload.autonomy_level,
                    payload.deploy_strategy,
                    payload.delivery_project_id,
                    session.get("user_id"),
                ),
            )
            run_id = cur.lastrowid
            await db.commit()

        # Fire-and-forget background execution (lives in event loop, not request scope).
        asyncio.create_task(_spawn_runner(run_id))

        logger.info("Pipeline run created: id=%s title=%r by user_id=%s",
                    run_id, payload.title, session.get("user_id"))

        return {
            "id": run_id,
            "status": "pending",
            "title": payload.title,
            "project_type": payload.project_type,
            "autonomy_level": payload.autonomy_level,
            "deploy_strategy": payload.deploy_strategy,
        }

    # ── GET /api/pipeline/runs ───────────────────────────────────────────

    @app.get("/api/pipeline/runs")
    async def pipeline_runs_list(
        status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        sql = "SELECT * FROM pipeline_runs"
        vals: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            vals.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        vals.extend([limit, offset])

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, vals)
            rows = await cur.fetchall()

        return {"runs": [_row_to_dict(r) for r in rows], "limit": limit, "offset": offset}

    # ── GET /api/pipeline/runs/{id} ──────────────────────────────────────

    @app.get("/api/pipeline/runs/{run_id}")
    async def pipeline_run_detail(
        run_id: int,
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(404, f"pipeline_runs id={run_id} not found")
        return _row_to_dict(row)

    # ── GET /api/pipeline/runs/{id}/events ───────────────────────────────

    @app.get("/api/pipeline/runs/{run_id}/events")
    async def pipeline_run_events(
        run_id: int,
        limit: int = Query(50, ge=1, le=500),
        since: int | None = Query(None, ge=0),
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """Return events for a run. `since` = id of last seen event for incremental polling."""
        sql = "SELECT * FROM pipeline_events WHERE run_id = ?"
        vals: list[Any] = [run_id]
        if since is not None:
            sql += " AND id > ?"
            vals.append(since)
        sql += " ORDER BY id DESC LIMIT ?"
        vals.append(limit)

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, vals)
            rows = await cur.fetchall()

        events = []
        for row in rows:
            d = _row_to_dict(row)
            # Deserialize payload_json into payload dict for client convenience.
            payload_raw = d.pop("payload_json", None)
            try:
                d["payload"] = json.loads(payload_raw) if payload_raw else {}
            except (TypeError, json.JSONDecodeError):
                d["payload"] = {}
            events.append(d)

        return {"events": events, "count": len(events), "limit": limit, "since": since}

    # ── POST /api/pipeline/runs/{id}/approve (T-3-012) ───────────────────

    @app.post("/api/pipeline/runs/{run_id}/approve")
    async def pipeline_run_approve(
        run_id: int,
        session: dict = Depends(require_role("owner")),
    ):
        """Approve a run that's in awaiting_approval status, resume execution."""
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT status FROM pipeline_runs WHERE id = ?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(404, f"pipeline_runs id={run_id} not found")
            current = row["status"]
            if current != "awaiting_approval":
                raise HTTPException(
                    400,
                    f"cannot approve: status is '{current}', expected 'awaiting_approval'",
                )

        # Log + emit event
        progress = PipelineProgress(run_id)
        await progress.emit_event(
            "approval_granted",
            payload={"by_user_id": session.get("user_id")},
            severity="info",
        )

        # Spawn resume in background — returns immediately.
        asyncio.create_task(_spawn_resume(run_id))
        logger.info("Pipeline run %s approved by user_id=%s", run_id, session.get("user_id"))
        return {"id": run_id, "status": "running", "message": "approved, resuming"}

    # ── WS /ws/pipeline/{run_id} (T-2-012) ───────────────────────────────

    @app.websocket("/ws/pipeline/{run_id}")
    async def pipeline_ws(
        websocket: WebSocket,
        run_id: int,
        token: str = Query(...),
    ):
        """WebSocket stream of events for a pipeline-run.

        Auth via ?token=<X-Auth-Token> query parameter (browsers can't set
        custom WS headers cross-origin). Token validated against hq_sessions
        (T-1-012). Owner or pm role required.

        Subscribes to PipelineProgress for run_id; events broadcast by
        emit_event() arrive as JSON messages: {id, run_id, event_type,
        severity, payload, created_at, ...}.

        Client may send arbitrary text (ignored) — used as a keepalive ping.
        On disconnect or error, subscription is cleaned up.
        """
        sess = await _ss_get_session(token)
        if sess is None or sess.get("role") not in ("owner", "pm"):
            # 1008 = policy violation. WS closes before accept().
            await websocket.close(code=1008)
            return

        await websocket.accept()
        PipelineProgress.subscribe(run_id, websocket)
        logger.info("WS connected: run_id=%s user_id=%s", run_id, sess.get("user_id"))
        try:
            # Loop receiving (and ignoring) text frames so we notice disconnects.
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001 — log and unsubscribe
            logger.warning("WS error on run %s: %s", run_id, e)
        finally:
            PipelineProgress.unsubscribe(run_id, websocket)
            logger.info("WS disconnected: run_id=%s user_id=%s", run_id, sess.get("user_id"))

    logger.info("Pipeline routes mounted: /api/pipeline/runs (CRUD + events) + /ws/pipeline/{run_id}")
