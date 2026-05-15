"""v1.1 endpoint tests — HI-1 (pause/resume/abort), HI-2 (files), HI-3 (sprints).

Reuses the session-scoped `service` + `auth_headers` fixtures from
test_pipeline_skeleton.py.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import pytest

# Reuse fixtures + constants from skeleton test file
from test_pipeline_skeleton import (  # type: ignore
    HTTP_BASE,
    DB,
    service,        # noqa: F401 — fixture re-export
    auth_headers,   # noqa: F401
)


@pytest.fixture(autouse=True)
def cleanup_v11_runs():
    db = sqlite3.connect(DB)
    db.execute(
        "DELETE FROM pipeline_events WHERE run_id IN "
        "(SELECT id FROM pipeline_runs WHERE title LIKE '__v11_test_%')"
    )
    db.execute(
        "DELETE FROM pipeline_sprints WHERE run_id IN "
        "(SELECT id FROM pipeline_runs WHERE title LIKE '__v11_test_%')"
    )
    db.execute("DELETE FROM pipeline_runs WHERE title LIKE '__v11_test_%'")
    db.commit()
    db.close()
    yield


def _create_run(headers: dict, suffix: str = "") -> int:
    body = {
        "title": f"__v11_test_{suffix}",
        "raw_idea": "v1.1 test",
        "project_type": "landing",
        "autonomy_level": 2,
        "deploy_strategy": "none",
    }
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs", json=body, headers=headers, timeout=10)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── HI-1: Pause / Resume / Abort ────────────────────────────────────────


def test_pause_resume_abort_flow(service, auth_headers):
    run_id = _create_run(auth_headers, "pra")
    time.sleep(1.5)  # let runner enter 'running'

    # Pause
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/pause", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "paused_user"

    # Pause again — invalid (status is paused_user, expected running/pending)
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/pause", headers=auth_headers, timeout=5)
    assert r.status_code == 400

    # Resume
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/resume", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    time.sleep(1)

    # Resume from non-paused state — invalid
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/resume", headers=auth_headers, timeout=5)
    assert r.status_code == 400

    # Pause again, then abort
    httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/pause", headers=auth_headers, timeout=5)
    time.sleep(0.5)
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/abort", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "aborted"

    # Abort already-terminal — invalid
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/abort", headers=auth_headers, timeout=5)
    assert r.status_code == 400


def test_pause_unknown_run(service, auth_headers):
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/9999999/pause", headers=auth_headers, timeout=5)
    assert r.status_code == 404


def test_action_endpoints_require_auth(service):
    for action in ("pause", "resume", "abort"):
        r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/1/{action}", timeout=5)
        assert r.status_code == 401


# ── HI-2: Files endpoint ────────────────────────────────────────────────


def test_files_list_and_content(service, auth_headers):
    run_id = _create_run(auth_headers, "files")
    # Wait for stub Phase 1-7 to finish (creates CLAUDE.md + final-report.md)
    deadline = time.time() + 30
    while time.time() < deadline:
        r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}", headers=auth_headers, timeout=5)
        if r.json()["status"] in ("done", "failed", "aborted"):
            break
        time.sleep(1)

    # List
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/files", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "files" in data
    assert data["count"] >= 1
    paths = [f["path"] for f in data["files"]]
    assert "CLAUDE.md" in paths

    # Content
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/files/CLAUDE.md",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    assert r.json()["content"]
    assert r.json()["path"] == "CLAUDE.md"


def test_files_traversal_blocked(service, auth_headers):
    run_id = _create_run(auth_headers, "trav")
    time.sleep(15)  # let stub finish so workspace exists

    # ../ traversal
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/files/../../etc/passwd",
                  headers=auth_headers, timeout=5)
    assert r.status_code in (400, 404)

    # Absolute path
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/files//etc/passwd",
                  headers=auth_headers, timeout=5)
    assert r.status_code in (400, 404)


def test_files_unknown_run(service, auth_headers):
    # Workspace doesn't exist for arbitrary high id
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/9999999/files",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200  # returns empty list, not 404
    assert r.json()["files"] == []


# ── HI-3: Sprints endpoint ──────────────────────────────────────────────


def test_sprints_empty(service, auth_headers):
    run_id = _create_run(auth_headers, "spr_empty")
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/sprints",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    # Stub mode — Phase 4 doesn't create real sprints
    assert r.json()["count"] == 0


def test_sprints_with_data(service, auth_headers):
    run_id = _create_run(auth_headers, "spr_data")
    # Insert fake sprint manually
    db = sqlite3.connect(DB)
    db.execute(
        "INSERT INTO pipeline_sprints "
        "(run_id, sprint_number, name, goal, status, tasks_total, tasks_done, spec_md) "
        "VALUES (?, 1, 'Test Sprint A', 'demo', 'done', 5, 5, '# Sprint 1\nspec')",
        (run_id,),
    )
    db.execute(
        "INSERT INTO pipeline_sprints "
        "(run_id, sprint_number, name, status) "
        "VALUES (?, 2, 'Test Sprint B', 'planned')",
        (run_id,),
    )
    db.commit()
    db.close()

    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/sprints",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    sprints = data["sprints"]
    # Ordered by sprint_number
    assert sprints[0]["sprint_number"] == 1
    assert sprints[0]["name"] == "Test Sprint A"
    assert sprints[0]["spec_md"]
    assert sprints[1]["sprint_number"] == 2
    assert sprints[1]["status"] == "planned"


# ── HI-6: Cost tracking ─────────────────────────────────────────────────


def test_tokens_used_column_present(service):
    """Migration _migrate_pipeline_v1_1 must add tokens_used column."""
    db = sqlite3.connect(DB)
    cols = [r[1] for r in db.execute("PRAGMA table_info(pipeline_runs)").fetchall()]
    db.close()
    assert "tokens_used" in cols


def test_tokens_used_in_run_response(service, auth_headers):
    run_id = _create_run(auth_headers, "tokens")
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    # In stub mode, no Claude calls -> tokens_used stays 0 (default)
    assert "tokens_used" in r.json()
    assert (r.json()["tokens_used"] or 0) == 0


# ── v1.3: Health, Rate Limits, Audit Log ────────────────────────────────


def test_health_endpoint(service, auth_headers):
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/health", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "counts_by_status" in data
    assert "recent_24h" in data
    for k in ("created_24h", "completed_24h", "failed_24h"):
        assert k in data["recent_24h"]
    assert isinstance(data["total_tokens_used"], int)
    assert isinstance(data["workspace_size_mb"], (int, float))
    assert isinstance(data["db_size_mb"], (int, float))
    assert "tmux_available" in data
    assert "claude_api_key" in data


def test_rate_limits_endpoint(service, auth_headers):
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/rate-limits", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    # Seeded models (opus, sonnet, haiku) — 3 rows
    for m in ("opus", "sonnet", "haiku"):
        assert m in data["models"]
        assert data["models"][m]["status"] in ("ok", "warning", "critical")
    assert "thresholds" in data
    assert data["thresholds"]["downgrade"] == 70
    assert data["thresholds"]["pause"] == 90
    assert isinstance(data["should_pause"], bool)


def test_audit_log_records_actions(service, auth_headers):
    run_id = _create_run(auth_headers, "audit")
    time.sleep(1)

    # Pause -> creates 'pause' audit entry
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs/{run_id}/pause",
                   headers=auth_headers, timeout=5)
    assert r.status_code == 200
    time.sleep(0.3)

    # Read audit log filtered by this run
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/audit-log?run_id={run_id}",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    entries = r.json()["entries"]
    actions = {e["action"] for e in entries}
    # Should at least see 'create' (from POST) and 'pause' (from /pause)
    assert "create" in actions
    assert "pause" in actions

    # Filter by action
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/audit-log?action=pause",
                  headers=auth_headers, timeout=5)
    assert r.status_code == 200
    for e in r.json()["entries"]:
        assert e["action"] == "pause"


def test_audit_log_owner_only(service):
    # Without auth: 401
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/audit-log", timeout=5)
    assert r.status_code == 401
