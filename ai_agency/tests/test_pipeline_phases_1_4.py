"""T-3-013: E2E for real Phase 1-4 with live Claude calls.

This test consumes real Claude tokens (5-15% of weekly Opus per run). It is
SKIPPED automatically when ANTHROPIC_API_KEY is not provisioned (current state
after Sprint 1 T-1-006 revoke).

To run manually after restoring the key:
    venv\\Scripts\\python.exe -m pytest tests\\test_pipeline_phases_1_4.py -v -s

Expected wall-time: 10-20 minutes for the full Phase 1-4 sequence.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / "venv" / "Scripts" / "python.exe")
MAIN = str(ROOT / "main.py")
DB = str(ROOT / "agency.db")
HTTP_BASE = "http://127.0.0.1:8000"

ADMIN_PASSWORD = os.environ.get("HQ_ADMIN_PASSWORD", "WMhA3aejzKjk03OHez8iSjtV")


def _api_key_real() -> bool:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return bool(key) and key != "disabled-not-used" and not key.startswith("sk-ant-api03-REPLACE")


SKIP_REASON = (
    "ANTHROPIC_API_KEY is not provisioned (currently 'disabled-not-used' per "
    "Sprint 1 T-1-006). Run with a real key to execute live Phase 1-4 against "
    "Claude API. Note: consumes 5-15% of weekly Opus."
)


@pytest.mark.skipif(not _api_key_real(), reason=SKIP_REASON)
def test_phases_1_4_end_to_end():
    """Live test: create run, wait for Phases 1-4, verify all deliverables."""
    env = os.environ.copy()
    env["WEB_ONLY"] = "true"
    env["PYTHONIOENCODING"] = "utf-8"
    # No PIPELINE_FORCE_STUB — we WANT real Claude calls here.

    log_path = ROOT / "_phase14_main.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [PYTHON, MAIN], cwd=str(ROOT), env=env,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        # Wait for service ready
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"{HTTP_BASE}/api/status", timeout=2).status_code in (200, 401):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("service did not become ready")

        # Login
        r = httpx.post(f"{HTTP_BASE}/api/auth/login",
                       json={"login": "owner", "password": ADMIN_PASSWORD}, timeout=10)
        token = r.json()["token"]
        H = {"X-Auth-Token": token}

        # Cleanup
        db = sqlite3.connect(DB)
        db.execute("DELETE FROM pipeline_events WHERE run_id IN "
                   "(SELECT id FROM pipeline_runs WHERE title LIKE '__live_phase14__%')")
        db.execute("DELETE FROM pipeline_sprints WHERE run_id IN "
                   "(SELECT id FROM pipeline_runs WHERE title LIKE '__live_phase14__%')")
        db.execute("DELETE FROM pipeline_runs WHERE title LIKE '__live_phase14__%'")
        db.commit()
        db.close()

        # Create run with autonomy_level=3 (no approvals needed)
        body = {
            "title": "__live_phase14__landing",
            "raw_idea": (
                "Простой одностраничный лендинг для AI-агентства Никиты Моруса "
                "с CTA на Telegram. Целевая аудитория — владельцы МСБ в РФ "
                "которые хотят автоматизировать рутину через AI."
            ),
            "project_type": "landing",
            "autonomy_level": 3,
            "deploy_strategy": "none",
        }
        r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs", json=body, headers=H, timeout=10)
        assert r.status_code == 201
        run_id = r.json()["id"]

        # Poll for completion (Phase 1-4 stub-free can take 10-20 min)
        deadline = time.time() + 25 * 60
        final = None
        while time.time() < deadline:
            r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}", headers=H, timeout=5)
            if r.status_code == 200:
                final = r.json()
                if final["status"] in ("done", "failed", "aborted"):
                    break
            time.sleep(15)

        assert final is not None
        assert final["status"] == "done", \
            f"expected done, got {final['status']}: {final.get('error_message')}"

        # Workspace deliverables
        ws = ROOT / "pipeline_workspaces" / str(run_id)
        assert (ws / "docs" / "prompt.md").exists()
        prd = ws / "docs" / "PRD.md"
        assert prd.exists() and prd.stat().st_size >= 2000, "PRD < 2KB"
        assert (ws / "docs" / "ARCHITECTURE.md").exists()
        assert (ws / "CLAUDE.md").exists()
        sprints_dir = ws / "docs" / "sprints"
        assert sprints_dir.exists()
        sprint_files = list(sprints_dir.glob("sprint-*.md"))
        assert len(sprint_files) >= 3, f"expected ≥3 sprints, got {len(sprint_files)}"

        # DB: pipeline_sprints rows
        db = sqlite3.connect(DB)
        n = db.execute("SELECT COUNT(*) FROM pipeline_sprints WHERE run_id=?",
                       (run_id,)).fetchone()[0]
        db.close()
        assert n >= 3
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
