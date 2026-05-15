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
from pipeline.audit import log_action as _audit_log, list_audit_log as _audit_list
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


def _tmux_available_safe() -> bool:
    try:
        from pipeline.tmux_manager import tmux_available
        return tmux_available()
    except Exception:
        return False


def _api_key_configured() -> bool:
    try:
        from pipeline.claude_runner import _api_key_available
        return _api_key_available()
    except Exception:
        return False


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

        await _audit_log(run_id=run_id, action="create",
                         actor=session.get("name") or "owner",
                         actor_id=session.get("user_id"),
                         source="http", to_status="pending",
                         details={"title": payload.title, "type": payload.project_type,
                                  "autonomy": payload.autonomy_level})

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

    # ── GET /api/pipeline/audit-log (v1.3) ───────────────────────────────

    @app.get("/api/pipeline/audit-log")
    async def pipeline_audit_log_list(
        run_id: int | None = Query(None),
        action: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _session: dict = Depends(require_role("owner")),
    ):
        """Owner-only audit trail of pipeline admin actions.

        Filters: ?run_id=N&action=pause&limit=&offset=
        """
        entries = await _audit_list(run_id=run_id, action=action, limit=limit, offset=offset)
        return {"entries": entries, "count": len(entries), "limit": limit, "offset": offset}

    # ── GET /api/pipeline/health (v1.3) ──────────────────────────────────

    @app.get("/api/pipeline/health")
    async def pipeline_health(
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """Aggregate health metrics for monitoring. No auth-bypass — same
        as other endpoints (owner|pm).

        Returns:
            counts_by_status: {pending, running, paused_*, awaiting_approval, done, failed, aborted}
            recent: {created_24h, completed_24h, failed_24h}
            workspace_size_mb: total size of pipeline_workspaces/ on disk
            db_size_mb: agency.db file size
            uptime_check: 'ok' if all critical components reachable
        """
        from pathlib import Path

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Status distribution
            cur = await db.execute(
                "SELECT status, COUNT(*) as n FROM pipeline_runs GROUP BY status"
            )
            counts = {r["status"]: r["n"] for r in await cur.fetchall()}

            # 24h activity
            cur = await db.execute(
                "SELECT "
                "  SUM(CASE WHEN datetime(created_at) > datetime('now', '-24 hours') THEN 1 ELSE 0 END) as created_24h, "
                "  SUM(CASE WHEN status='done' AND datetime(completed_at) > datetime('now', '-24 hours') THEN 1 ELSE 0 END) as done_24h, "
                "  SUM(CASE WHEN status='failed' AND datetime(completed_at) > datetime('now', '-24 hours') THEN 1 ELSE 0 END) as failed_24h "
                "FROM pipeline_runs"
            )
            row = await cur.fetchone()
            recent = {
                "created_24h": row["created_24h"] or 0,
                "completed_24h": row["done_24h"] or 0,
                "failed_24h": row["failed_24h"] or 0,
            }

            # Total tokens used (cumulative across all runs)
            cur = await db.execute("SELECT COALESCE(SUM(tokens_used), 0) FROM pipeline_runs")
            (total_tokens,) = await cur.fetchone()

        # Disk metrics (best-effort, never raise)
        ws_size_mb = 0.0
        try:
            ws_root = Path(DB_PATH).parent / "pipeline_workspaces"
            if ws_root.exists():
                ws_size_mb = round(
                    sum(f.stat().st_size for f in ws_root.rglob("*") if f.is_file()) / 1_048_576,
                    2,
                )
        except Exception:
            pass

        db_size_mb = 0.0
        try:
            db_size_mb = round(Path(DB_PATH).stat().st_size / 1_048_576, 2)
        except Exception:
            pass

        return {
            "status": "ok",
            "counts_by_status": counts,
            "recent_24h": recent,
            "total_tokens_used": int(total_tokens or 0),
            "workspace_size_mb": ws_size_mb,
            "db_size_mb": db_size_mb,
            "tmux_available": _tmux_available_safe(),
            "claude_api_key": "configured" if _api_key_configured() else "disabled",
        }

    # ── GET /api/pipeline/rate-limits (v1.2) ─────────────────────────────

    @app.get("/api/pipeline/rate-limits")
    async def pipeline_rate_limits(
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """Current rate limit state per model (Sprint 4 RateLimitManager).

        Returns {model: {weekly_used, weekly_limit, pct, reset_at, last_updated}}
        plus a derived `status` per model:
        - 'ok'        — pct < 70
        - 'warning'   — pct >= 70 (downgrade kicks in)
        - 'critical'  — pct >= 90 (pause threshold)
        """
        from pipeline.rate_limit import (
            RateLimitManager,
            WEEKLY_DOWNGRADE_THRESHOLD,
            WEEKLY_PAUSE_THRESHOLD,
        )
        rl = RateLimitManager()
        state = await rl.get_state()
        out = {}
        for model, s in state.items():
            pct = s.get("pct", 0)
            if pct >= WEEKLY_PAUSE_THRESHOLD:
                status = "critical"
            elif pct >= WEEKLY_DOWNGRADE_THRESHOLD:
                status = "warning"
            else:
                status = "ok"
            out[model] = {**s, "status": status}
        return {
            "models": out,
            "should_pause": await rl.should_pause(),
            "thresholds": {
                "downgrade": WEEKLY_DOWNGRADE_THRESHOLD,
                "pause": WEEKLY_PAUSE_THRESHOLD,
            },
        }

    # ── GET /api/pipeline/runs/{id}/sprints (HI-3, v1.1) ─────────────────

    @app.get("/api/pipeline/runs/{run_id}/sprints")
    async def pipeline_run_sprints(
        run_id: int,
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """List sprints (planned/active/done/failed) for a pipeline-run.

        Each sprint includes status, task counts, timing. spec_md content
        is included so UI can render the full sprint description without
        another round-trip.
        """
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, sprint_number, name, goal, status, "
                "tasks_total, tasks_done, tasks_failed, "
                "started_at, completed_at, created_at, spec_md "
                "FROM pipeline_sprints WHERE run_id = ? "
                "ORDER BY sprint_number",
                (run_id,),
            )
            rows = await cur.fetchall()
        return {"run_id": run_id, "sprints": [_row_to_dict(r) for r in rows], "count": len(rows)}

    # ── GET /api/pipeline/runs/{id}/files (HI-2, v1.1) ───────────────────

    @app.get("/api/pipeline/runs/{run_id}/files")
    async def pipeline_run_files_list(
        run_id: int,
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """List markdown files in workspace docs/ for the run."""
        from pipeline.workspace import PipelineWorkspace
        ws = PipelineWorkspace(run_id)
        if not ws.exists():
            return {"run_id": run_id, "files": []}

        from pathlib import Path
        files: list[dict] = []
        # Top-level CLAUDE.md
        claude_md = ws.path / "CLAUDE.md"
        if claude_md.exists():
            files.append({
                "path": "CLAUDE.md",
                "size": claude_md.stat().st_size,
                "category": "root",
            })
        # docs/*.md
        if ws.docs_path.exists():
            for f in sorted(ws.docs_path.glob("*.md")):
                files.append({
                    "path": f"docs/{f.name}",
                    "size": f.stat().st_size,
                    "category": "docs",
                })
            # docs/sprints/*.md
            sprints_dir = ws.docs_path / "sprints"
            if sprints_dir.exists():
                for f in sorted(sprints_dir.glob("*.md")):
                    files.append({
                        "path": f"docs/sprints/{f.name}",
                        "size": f.stat().st_size,
                        "category": "sprints",
                    })
        return {"run_id": run_id, "files": files, "count": len(files)}

    @app.get("/api/pipeline/runs/{run_id}/files/{file_path:path}")
    async def pipeline_run_file_content(
        run_id: int,
        file_path: str,
        _session: dict = Depends(require_role("owner", "pm")),
    ):
        """Return raw text content of a file from the workspace.

        Path is restricted to the workspace root (no `..` traversal allowed).
        Only files under .md extension or no extension (e.g. CLAUDE.md) are
        served — this is a workspace browser, not a generic file API.
        """
        from pipeline.workspace import PipelineWorkspace
        from pathlib import Path

        ws = PipelineWorkspace(run_id)
        if not ws.exists():
            raise HTTPException(404, f"workspace for run {run_id} does not exist")

        # Security: resolve and ensure path is inside workspace root.
        target = (ws.path / file_path).resolve()
        try:
            target.relative_to(ws.path.resolve())
        except ValueError:
            raise HTTPException(400, "path traversal blocked")

        if not target.exists() or not target.is_file():
            raise HTTPException(404, f"file not found: {file_path}")

        # Only serve markdown or extension-less files (CLAUDE.md, README, etc.).
        if target.suffix not in ("", ".md", ".txt"):
            raise HTTPException(400, f"file type not allowed: {target.suffix}")

        # Cap size at 1 MB to avoid streaming giant files.
        if target.stat().st_size > 1_048_576:
            raise HTTPException(413, "file too large (>1 MB)")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "file is not utf-8 text")

        return {
            "run_id": run_id,
            "path": file_path,
            "size": target.stat().st_size,
            "content": content,
        }

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

        # Log + emit event + audit
        progress = PipelineProgress(run_id)
        await progress.emit_event(
            "approval_granted",
            payload={"by_user_id": session.get("user_id")},
            severity="info",
        )
        await _audit_log(run_id=run_id, action="approve",
                         actor=session.get("name") or "owner",
                         actor_id=session.get("user_id"),
                         source="http", from_status="awaiting_approval", to_status="running")

        # Spawn resume in background — returns immediately.
        asyncio.create_task(_spawn_resume(run_id))
        logger.info("Pipeline run %s approved by user_id=%s", run_id, session.get("user_id"))
        return {"id": run_id, "status": "running", "message": "approved, resuming"}

    # ── POST /api/pipeline/runs/{id}/pause | resume | abort (HI-1, post-v1.0) ────

    @app.post("/api/pipeline/runs/{run_id}/pause")
    async def pipeline_run_pause(
        run_id: int,
        session: dict = Depends(require_role("owner")),
    ):
        """Manually pause a running pipeline-run.

        Sets status='paused_user' + pause_reason. The runner sees this on its
        next phase boundary (cooperative — phases don't pre-empt mid-call).
        """
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT status FROM pipeline_runs WHERE id=?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(404, f"pipeline_runs id={run_id} not found")
            current = row["status"]
            if current not in ("running", "pending"):
                raise HTTPException(
                    400, f"cannot pause: status='{current}', expected running/pending",
                )
            await db.execute(
                "UPDATE pipeline_runs SET status='paused_user', "
                "paused_at=CURRENT_TIMESTAMP, pause_reason='manual pause by owner' "
                "WHERE id=?",
                (run_id,),
            )
            await db.commit()
        await PipelineProgress(run_id).emit_event(
            "paused", payload={"reason": "manual", "by_user_id": session.get("user_id")},
            severity="warning",
        )
        await _audit_log(run_id=run_id, action="pause",
                         actor=session.get("name") or "owner",
                         actor_id=session.get("user_id"),
                         source="http", from_status=current, to_status="paused_user")
        logger.info("Pipeline run %s paused by user_id=%s", run_id, session.get("user_id"))
        return {"id": run_id, "status": "paused_user"}

    @app.post("/api/pipeline/runs/{run_id}/resume")
    async def pipeline_run_resume(
        run_id: int,
        session: dict = Depends(require_role("owner")),
    ):
        """Resume from any paused state (paused_user, paused_rate_limit, awaiting_approval)."""
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT status FROM pipeline_runs WHERE id=?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(404, f"pipeline_runs id={run_id} not found")
            current = row["status"]
            if current not in ("paused_user", "paused_rate_limit", "awaiting_approval"):
                raise HTTPException(
                    400,
                    f"cannot resume: status='{current}', expected paused_user/paused_rate_limit/awaiting_approval",
                )
        await PipelineProgress(run_id).emit_event(
            "resumed", payload={"by_user_id": session.get("user_id"), "from_status": current},
        )
        await _audit_log(run_id=run_id, action="resume",
                         actor=session.get("name") or "owner",
                         actor_id=session.get("user_id"),
                         source="http", from_status=current, to_status="running")
        asyncio.create_task(_spawn_resume(run_id))
        logger.info("Pipeline run %s resumed by user_id=%s", run_id, session.get("user_id"))
        return {"id": run_id, "status": "running", "message": f"resumed from {current}"}

    @app.post("/api/pipeline/runs/{run_id}/abort")
    async def pipeline_run_abort(
        run_id: int,
        session: dict = Depends(require_role("owner")),
    ):
        """Terminate a run. Marks status='aborted'. Workspace is preserved on disk
        for audit (manual cleanup via PipelineWorkspace.cleanup() if needed)."""
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT status FROM pipeline_runs WHERE id=?", (run_id,))
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(404, f"pipeline_runs id={run_id} not found")
            current = row["status"]
            if current in ("done", "aborted", "failed"):
                raise HTTPException(
                    400, f"cannot abort: already terminal ('{current}')",
                )
            await db.execute(
                "UPDATE pipeline_runs SET status='aborted', "
                "completed_at=CURRENT_TIMESTAMP, error_message='aborted by owner' "
                "WHERE id=?",
                (run_id,),
            )
            await db.commit()
        await PipelineProgress(run_id).emit_event(
            "run_aborted", payload={"by_user_id": session.get("user_id"), "from_status": current},
            severity="warning",
        )
        await _audit_log(run_id=run_id, action="abort",
                         actor=session.get("name") or "owner",
                         actor_id=session.get("user_id"),
                         source="http", from_status=current, to_status="aborted")
        logger.info("Pipeline run %s aborted by user_id=%s (was %s)",
                    run_id, session.get("user_id"), current)
        return {"id": run_id, "status": "aborted"}

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
