"""T-2-014 (Sprint 2): pytest E2E for the pipeline skeleton.

Spawns a real `main.py` in a subprocess (WEB_ONLY mode) and exercises the
HTTP/WebSocket surface end-to-end. Pytest fixtures handle setup/teardown.

Run from `ai_agency/`:
    venv\\Scripts\\python.exe -m pytest tests\\test_pipeline_skeleton.py -v

Or directly:
    venv\\Scripts\\python.exe tests\\test_pipeline_skeleton.py
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

# ai_agency/ root (one up from tests/)
ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / "venv" / "Scripts" / "python.exe")
MAIN = str(ROOT / "main.py")
DB = str(ROOT / "agency.db")
HTTP_BASE = "http://127.0.0.1:8000"

ADMIN_PASSWORD = os.environ.get("HQ_ADMIN_PASSWORD", "WMhA3aejzKjk03OHez8iSjtV")

ENV = os.environ.copy()
ENV["WEB_ONLY"] = "true"
ENV["PYTHONIOENCODING"] = "utf-8"
# Sprint 3+: phases now make real Claude calls by default. Tests force stub
# mode so they don't burn API tokens (and don't fail when key=disabled-not-used).
ENV["PIPELINE_FORCE_STUB"] = "true"


# ── Fixtures ─────────────────────────────────────────────────────────────


def _wait_ready(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{HTTP_BASE}/api/status", timeout=2.0)
            if r.status_code in (200, 401):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def service():
    """Start ai_agency main.py in WEB_ONLY mode for the test session."""
    log_path = ROOT / "_pytest_main.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [PYTHON, MAIN],
        cwd=str(ROOT),
        env=ENV,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    if not _wait_ready():
        proc.kill()
        log.close()
        pytest.skip(f"Service did not become ready (see {log_path})")
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    log.close()


@pytest.fixture(scope="session")
def auth_headers(service):
    r = httpx.post(
        f"{HTTP_BASE}/api/auth/login",
        json={"login": "owner", "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return {"X-Auth-Token": r.json()["token"]}


@pytest.fixture(autouse=True)
def cleanup_test_runs():
    """Remove any prior __pytest_pipeline__* runs before each test."""
    db = sqlite3.connect(DB)
    db.execute(
        "DELETE FROM pipeline_events WHERE run_id IN "
        "(SELECT id FROM pipeline_runs WHERE title LIKE '__pytest_pipeline__%')"
    )
    db.execute("DELETE FROM pipeline_runs WHERE title LIKE '__pytest_pipeline__%'")
    db.commit()
    db.close()
    yield


# ── Tests ────────────────────────────────────────────────────────────────


def test_pipeline_run_lifecycle(service, auth_headers):
    """Full lifecycle: create -> phases run -> done -> events present."""
    # 1. POST creates the run, returns 201 with id
    body = {
        "title": "__pytest_pipeline__landing",
        "raw_idea": "build me a landing page",
        "project_type": "landing",
        "autonomy_level": 2,
        "deploy_strategy": "none",
    }
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs", json=body, headers=auth_headers, timeout=10)
    assert r.status_code == 201, r.text
    data = r.json()
    run_id = data["id"]
    assert data["status"] == "pending"

    # 2. Poll up to 30 seconds for terminal status (7 stub phases x 2s = 14s + overhead)
    deadline = time.time() + 30
    final = None
    while time.time() < deadline:
        r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}", headers=auth_headers, timeout=5)
        if r.status_code == 200:
            final = r.json()
            if final["status"] in ("done", "failed", "aborted"):
                break
        time.sleep(1)

    assert final is not None, "no response from detail endpoint"
    assert final["status"] == "done", f"expected done, got {final['status']}: {final.get('error_message')}"
    assert final["current_phase"] == "handoff"

    # 3. Events: 16 baseline (7 phase_started + 7 phase_completed + run_started +
    # run_completed) plus extras emitted by some phases (validation_inspection,
    # handoff_complete, sprint_started/completed if any sprints).
    r = httpx.get(
        f"{HTTP_BASE}/api/pipeline/runs/{run_id}/events?limit=100",
        headers=auth_headers, timeout=5,
    )
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) >= 16, f"expected >=16 events, got {len(events)}: {[e['event_type'] for e in events]}"

    type_counts: dict[str, int] = {}
    for e in events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1
    assert type_counts["phase_started"] == 7
    assert type_counts["phase_completed"] == 7
    assert type_counts["run_started"] == 1
    assert type_counts["run_completed"] == 1
    # Sprint 4 phases emit extra signals (not always present — Phase 5 only
    # emits sprint_* if pipeline_sprints rows exist for the run).
    assert "handoff_complete" in type_counts

    # Phase order: events come back DESC by id; verify completed-phase order chronologically.
    completed_phases = [
        e["payload"]["phase"] for e in events if e["event_type"] == "phase_completed"
    ]
    completed_phases.reverse()  # back to chronological
    assert completed_phases == [
        "prompt", "prd", "architecture", "sprints",
        "execution", "validation", "handoff",
    ]

    # Sample payload structure
    sample = next(e for e in events if e["event_type"] == "phase_completed")
    assert isinstance(sample["payload"], dict)
    assert "phase" in sample["payload"]


def test_pipeline_run_listing_and_filter(service, auth_headers):
    """List endpoint returns the run, status filter works."""
    body = {
        "title": "__pytest_pipeline__list_test",
        "raw_idea": "x",
        "project_type": "landing",
        "autonomy_level": 2,
        "deploy_strategy": "none",
    }
    r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs", json=body, headers=auth_headers, timeout=10)
    run_id = r.json()["id"]

    # Wait briefly so status moves from pending -> running
    time.sleep(2)

    # Listing without filter
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs?limit=200", headers=auth_headers, timeout=5)
    assert r.status_code == 200
    listing = r.json()
    ids = [run["id"] for run in listing["runs"]]
    assert run_id in ids

    # Wait for completion to test status filter
    deadline = time.time() + 25
    while time.time() < deadline:
        r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}", headers=auth_headers, timeout=5)
        if r.json()["status"] in ("done", "failed"):
            break
        time.sleep(1)

    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs?status=done&limit=200", headers=auth_headers, timeout=5)
    done_ids = [run["id"] for run in r.json()["runs"]]
    assert run_id in done_ids


def test_pipeline_unauthorized(service):
    """Endpoints without auth return 401."""
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs", timeout=5)
    assert r.status_code == 401

    r = httpx.post(
        f"{HTTP_BASE}/api/pipeline/runs",
        json={"title": "x", "raw_idea": "x", "project_type": "landing"},
        timeout=5,
    )
    assert r.status_code == 401


def test_pipeline_run_not_found(service, auth_headers):
    r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/9999999", headers=auth_headers, timeout=5)
    assert r.status_code == 404


if __name__ == "__main__":
    # Allow direct run for quick local check (without pytest collecting)
    sys.exit(pytest.main([__file__, "-v"]))
