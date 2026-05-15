"""Release gate end-to-end smoke test."""
import httpx
import sys
import json

BASE = "http://127.0.0.1:8000"
PW = {"X-Admin-Password": "Admin2024", "Content-Type": "application/json"}

results = []

def log(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append((ok, label, detail))

with httpx.Client(base_url=BASE, headers=PW, timeout=15) as c:
    # --- Dashboard ---
    r = c.get("/api/dashboard/stats")
    log("GET /api/dashboard/stats", r.status_code == 200, f"HTTP {r.status_code}, pending={r.json().get('pending_payments_total') if r.status_code==200 else '-'}")

    r = c.get("/api/dashboard/focus")
    log("GET /api/dashboard/focus", r.status_code == 200)

    r = c.get("/api/tasks-v2/metrics")
    log("GET /api/tasks-v2/metrics", r.status_code == 200)

    # --- Create client ---
    payload = {"name": "RELEASE_GATE_TEST", "service_type": "комплекс", "status": "active", "total_amount": 50000}
    r = c.post("/api/clients", json=payload)
    ok = r.status_code == 200
    cid = r.json().get("id") if ok else None
    log("POST /api/clients (with Cyrillic + custom service_type)", ok, f"id={cid}")

    # --- Update client ---
    if cid:
        r = c.put(f"/api/clients/{cid}", json={"paid_amount": 20000})
        log("PUT /api/clients/{id}", r.status_code == 200)

    # --- Create project without client ---
    r = c.post("/api/projects", json={"name": "Орфанный проект", "stage": "discovery", "progress": 10})
    pid_orphan = r.json().get("id") if r.status_code == 200 else None
    log("POST /api/projects (no client_id)", pid_orphan is not None, f"id={pid_orphan}")

    # --- Create project with client ---
    if cid:
        r = c.post("/api/projects", json={"client_id": cid, "name": "Клиентский проект", "stage": "development", "progress": 50})
        pid2 = r.json().get("id") if r.status_code == 200 else None
        log("POST /api/projects (with client_id)", pid2 is not None, f"id={pid2}")

        # --- Add project task ---
        if pid2:
            r = c.post(f"/api/projects/{pid2}/tasks", json={"title": "Проверка задачи проекта"})
            tid = r.json().get("id") if r.status_code == 200 else None
            log("POST /api/projects/{id}/tasks", tid is not None, f"id={tid}")

            # --- GET project ---
            r = c.get(f"/api/projects/{pid2}")
            log("GET /api/projects/{id}", r.status_code == 200)

            # --- GET project tasks ---
            r = c.get(f"/api/projects/{pid2}/tasks")
            log("GET /api/projects/{id}/tasks", r.status_code == 200 and len(r.json().get("tasks", [])) >= 1)

            # --- Edit project (full fields) ---
            r = c.put(f"/api/projects/{pid2}", json={
                "name": "Обновлённое имя",
                "progress": 75,
                "executor": "Команда QA",
                "budget": 150000,
                "priority": "высокий",
                "notes": "Проверено автоматом"
            })
            log("PUT /api/projects/{id} (executor/budget/priority/notes)", r.status_code == 200)

            # --- Verify fields saved ---
            r = c.get(f"/api/projects/{pid2}")
            p = r.json() if r.status_code == 200 else {}
            log("Project executor persisted", p.get("executor") == "Команда QA", repr(p.get("executor")))
            log("Project budget persisted", p.get("budget") == 150000, repr(p.get("budget")))
            log("Project priority persisted", p.get("priority") == "высокий", repr(p.get("priority")))

        # --- Add payment ---
        r = c.post(f"/api/clients/{cid}/payments", json={"amount": 25000, "status": "ожидается", "description": "Этап 1"})
        log("POST /api/clients/{id}/payments", r.status_code == 200)

        # --- Archive client ---
        r = c.post(f"/api/clients/{cid}/archive")
        log("POST /api/clients/{id}/archive", r.status_code == 200)

        # --- List archived ---
        r = c.get("/api/clients/archived")
        ids = [cl.get("id") for cl in r.json().get("clients", [])]
        log("GET /api/clients/archived contains our client", cid in ids)

        # --- Restore ---
        r = c.post(f"/api/clients/{cid}/restore")
        log("POST /api/clients/{id}/restore", r.status_code == 200)

    # --- Create task-v2 ---
    r = c.post("/api/tasks-v2", json={"title": "Тест V2 задача", "priority": "высокий"})
    t2 = r.json().get("id") if r.status_code == 200 else None
    log("POST /api/tasks-v2", t2 is not None, f"id={t2}")

    if t2:
        r = c.put(f"/api/tasks-v2/{t2}", json={"status": "in_progress", "description": "Обновили"})
        log("PUT /api/tasks-v2/{id}", r.status_code == 200)

        r = c.delete(f"/api/tasks-v2/{t2}")
        log("DELETE /api/tasks-v2/{id}", r.status_code == 200)

    # --- Kanban ---
    r = c.post("/api/kanban", json={"title": "Канбан-карточка", "column_id": "todo", "content": "тест"})
    kid = r.json().get("id") if r.status_code == 200 else None
    log("POST /api/kanban", kid is not None, f"id={kid}")
    if kid:
        r = c.post(f"/api/kanban/{kid}/move", json={"column_id": "in_progress"})
        log("POST /api/kanban/{id}/move", r.status_code == 200)
        r = c.delete(f"/api/kanban/{kid}")
        log("DELETE /api/kanban/{id}", r.status_code == 200)

    # --- Cleanup: delete test client (cascade) ---
    if cid:
        r = c.delete(f"/api/clients/{cid}")
        log("DELETE /api/clients/{id} (cascade)", r.status_code == 200)

        # Verify project gone (or unlinked)
        if 'pid2' in dir() and pid2:
            r = c.get(f"/api/projects/{pid2}")
            # Either 404 (cascade) OR 200 with client_id=None (nullify)
            if r.status_code == 404:
                log("Project cascade-deleted or orphaned-OK", True, "404")
            elif r.status_code == 200:
                p = r.json()
                log("Project survived with client_id=None", p.get("client_id") is None, f"client_id={p.get('client_id')}")
            else:
                log("Project state after client delete", False, f"HTTP {r.status_code}")

    # --- Cleanup orphan project ---
    if pid_orphan:
        r = c.delete(f"/api/projects/{pid_orphan}")
        log("DELETE /api/projects/{id} (orphan cleanup)", r.status_code == 200)

# --- Summary ---
passed = sum(1 for r in results if r[0])
failed = sum(1 for r in results if not r[0])
print(f"\n=== RESULT: {passed} PASS / {failed} FAIL ===")
sys.exit(0 if failed == 0 else 1)
