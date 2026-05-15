"""T-4-012 (Sprint 4): full end-to-end pipeline test.

Runs a complete pipeline-run through all 7 phases against live Claude API.
SKIPPED automatically when ANTHROPIC_API_KEY is not real.

Wall-time: 60-120 minutes. Token cost: 30-50% of weekly Opus budget.
DO NOT run in CI without explicit budget approval.

Manual run after ANTHROPIC_API_KEY is restored:
    venv\\Scripts\\python.exe -m pytest tests/test_pipeline_e2e.py -v -s --timeout=10800
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
    "Full pipeline E2E requires ANTHROPIC_API_KEY (currently 'disabled-not-used' "
    "per Sprint 1 T-1-006) and burns ~30-50% of weekly Opus. Run manually with "
    "a real key + explicit budget approval."
)


@pytest.mark.skipif(not _api_key_real(), reason=SKIP_REASON)
@pytest.mark.timeout(10800)  # 3 hours
def test_full_pipeline_e2e_landing():
    """Run a real landing pipeline through all 7 phases. Verify deliverables."""
    env = os.environ.copy()
    env["WEB_ONLY"] = "true"
    env["PYTHONIOENCODING"] = "utf-8"
    # No PIPELINE_FORCE_STUB — full real run.

    proc = subprocess.Popen(
        [PYTHON, MAIN], cwd=str(ROOT), env=env,
        stdout=open(ROOT / "_e2e_main.log", "wb"), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        # Wait ready
        for _ in range(60):
            try:
                if httpx.get(f"{HTTP_BASE}/api/status", timeout=2).status_code in (200, 401):
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Login
        r = httpx.post(f"{HTTP_BASE}/api/auth/login",
                       json={"login": "owner", "password": ADMIN_PASSWORD}, timeout=10)
        assert r.status_code == 200
        token = r.json()["token"]
        H = {"X-Auth-Token": token}

        # Cleanup prior __e2e_full__ runs
        db = sqlite3.connect(DB)
        db.execute("DELETE FROM pipeline_events WHERE run_id IN "
                   "(SELECT id FROM pipeline_runs WHERE title LIKE '__e2e_full__%')")
        db.execute("DELETE FROM pipeline_sprints WHERE run_id IN "
                   "(SELECT id FROM pipeline_runs WHERE title LIKE '__e2e_full__%')")
        db.execute("DELETE FROM pipeline_runs WHERE title LIKE '__e2e_full__%'")
        db.commit()
        db.close()

        # Create run with autonomy_level=3 → no approvals needed
        body = {
            "title": "__e2e_full__landing",
            "raw_idea": (
                "Простой landing для AI-агентства Никиты Моруса с CTA на Telegram. "
                "Целевая аудитория — владельцы МСБ в РФ (5-100 человек), которые "
                "хотят автоматизировать рутину через AI. Контент: hero, проблема/решение, "
                "3 кейса, FAQ, CTA на Telegram чат с владельцем."
            ),
            "project_type": "landing",
            "autonomy_level": 3,
            "deploy_strategy": "none",
        }
        r = httpx.post(f"{HTTP_BASE}/api/pipeline/runs", json=body, headers=H, timeout=10)
        assert r.status_code == 201
        run_id = r.json()["id"]
        print(f"\n>>> Started full pipeline run id={run_id}")

        # Poll up to 2 hours
        deadline = time.time() + 2 * 60 * 60
        final = None
        last_phase = None
        while time.time() < deadline:
            r = httpx.get(f"{HTTP_BASE}/api/pipeline/runs/{run_id}", headers=H, timeout=10)
            if r.status_code == 200:
                final = r.json()
                if final["current_phase"] != last_phase:
                    print(f">>> Phase: {final['current_phase']} (status={final['status']})")
                    last_phase = final["current_phase"]
                if final["status"] in ("done", "failed", "aborted", "review"):
                    break
            time.sleep(20)

        assert final is not None
        assert final["status"] in ("done", "review"), \
            f"unexpected final status: {final['status']}: {final.get('error_message')}"

        # Workspace deliverables
        ws = ROOT / "pipeline_workspaces" / str(run_id)
        for fn in ("docs/prompt.md", "docs/PRD.md", "docs/ARCHITECTURE.md",
                   "CLAUDE.md", "docs/final-report.md"):
            assert (ws / fn).exists(), f"missing {fn}"
        sprints = list((ws / "docs" / "sprints").glob("sprint-*.md"))
        assert len(sprints) >= 3

        # DB sanity
        db = sqlite3.connect(DB)
        n_sprints = db.execute("SELECT COUNT(*) FROM pipeline_sprints WHERE run_id=?",
                               (run_id,)).fetchone()[0]
        n_events = db.execute("SELECT COUNT(*) FROM pipeline_events WHERE run_id=?",
                              (run_id,)).fetchone()[0]
        db.close()
        assert n_sprints >= 3
        assert n_events >= 30  # at least 7 phases × 2 events + per-sprint events
        print(f"\n>>> SUCCESS: run id={run_id}, {n_sprints} sprints, {n_events} events")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
