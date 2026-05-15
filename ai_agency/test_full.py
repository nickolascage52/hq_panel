"""Full API smoke suite for HQ backend. Run with server: uvicorn main:app."""
from __future__ import annotations

import sys

import httpx

BASE = "http://localhost:8000"
H = {"X-Admin-Password": "Admin2024", "Content-Type": "application/json"}
passed: list[str] = []
failed: list[str] = []


def t(
    name: str,
    method: str,
    url: str,
    body: dict | None = None,
    expect: int = 200,
    check=None,
):
    try:
        fn = getattr(httpx, method.lower())
        kw: dict = {"headers": H, "timeout": 15}
        if body is not None:
            kw["json"] = body
        r = fn(f"{BASE}{url}", **kw)
        ok = r.status_code == expect
        if ok and check:
            try:
                payload = r.json()
            except Exception:
                ok = False
                failed.append(f"FAIL {name}: invalid JSON | {r.text[:200]}")
                return r
            ok = bool(check(payload))
        msg = f"{'OK' if ok else 'FAIL'} {name}"
        if not ok:
            msg += f": got {r.status_code} | {r.text[:140]}"
        (passed if ok else failed).append(msg)
        return r
    except Exception as e:
        failed.append(f"ERR {name}: {e}")
        return None


# AUTH
t("Auth legacy password", "GET", "/api/dashboard/stats")
r = t("Auth login", "POST", "/api/auth/login", {"login": "owner", "password": "Admin2024"})
if r and r.status_code == 200:
    token = r.json().get("token", "")
    if token:
        r2 = httpx.get(f"{BASE}/api/dashboard/stats", headers={"X-Auth-Token": token}, timeout=10)
        (passed if r2.status_code == 200 else failed).append(
            f"{'OK' if r2.status_code == 200 else 'FAIL'} Auth token"
        )
r3 = httpx.post(f"{BASE}/api/clients", json={"name": "x"}, headers={"Content-Type": "application/json"}, timeout=10)
(passed if r3.status_code == 401 else failed).append(
    f"{'OK' if r3.status_code == 401 else 'FAIL'} Auth no token -> 401 (got {r3.status_code})"
)


# DASHBOARD
t(
    "Dashboard stats",
    "GET",
    "/api/dashboard/stats",
    check=lambda d: "expected_payments" in d and "active_clients" in d,
)
r1 = httpx.get(f"{BASE}/api/dashboard/stats", headers=H, timeout=10)
r2 = httpx.get(f"{BASE}/api/dashboard/focus", headers=H, timeout=10)
if r1.status_code == 200 and r2.status_code == 200:
    j1 = r1.json()
    j2 = r2.json()
    ep1 = j1.get("expected_payments", -1)
    ep2 = j2.get("expected_payments", -2)
    (passed if ep1 == ep2 else failed).append(
        f"{'OK' if ep1 == ep2 else 'FAIL'} Dashboard payments consistent: stats={ep1} focus={ep2}"
    )


# CRM
t(
    "CRM list clients",
    "GET",
    "/api/clients",
    check=lambda d: isinstance(d, dict) and isinstance(d.get("clients"), list),
)
rc = t("CRM create client", "POST", "/api/clients", {"name": "QA_TEST"}, check=lambda d: "id" in d)
cid = rc.json().get("id") if rc and rc.status_code == 200 else None
if cid:
    t("CRM update client", "PUT", f"/api/clients/{cid}", {"next_action": "test"})
    t("CRM archive", "POST", f"/api/clients/{cid}/archive")
    t("CRM restore", "POST", f"/api/clients/{cid}/restore")

# PROJECTS
rp = t("Projects create no client", "POST", "/api/projects", {"name": "QA_PROJ"}, check=lambda d: "id" in d)
pid = rp.json().get("id") if rp and rp.status_code == 200 else None
if pid:
    t("Projects update", "PUT", f"/api/projects/{pid}", {"name": "QA_UPDATED"})

# TASKS V2
rt = t("Tasks create", "POST", "/api/tasks-v2", {"title": "QA_TASK"}, check=lambda d: "id" in d)
tid = rt.json().get("id") if rt and rt.status_code == 200 else None
if tid:
    t("Tasks update", "PUT", f"/api/tasks-v2/{tid}", {"status": "в работе"})
    t(
        "Tasks GET one",
        "GET",
        f"/api/tasks-v2/{tid}",
        check=lambda d: "checklist" in d and "comments" in d,
    )
    rc2 = t(
        "Tasks add checklist",
        "POST",
        f"/api/tasks-v2/{tid}/checklist",
        {"title": "item"},
        check=lambda d: "id" in d,
    )
    if rc2 and rc2.status_code == 200:
        iid = rc2.json().get("id")
        t("Tasks toggle checklist", "PUT", f"/api/tasks-v2/checklist/{iid}", {"is_completed": True})
    t("Tasks add comment", "POST", f"/api/tasks-v2/{tid}/comments", {"body": "test"})
    t("Tasks metrics", "GET", "/api/tasks-v2/metrics", check=lambda d: "open" in d)
    t("Tasks delete", "DELETE", f"/api/tasks-v2/{tid}")

# KANBAN
rk = t(
    "Kanban create",
    "POST",
    "/api/kanban",
    {"title": "QA_CARD", "column_id": "inbox"},
    check=lambda d: "id" in d,
)
kid = rk.json().get("id") if rk and rk.status_code == 200 else None
if kid:
    t("Kanban move", "POST", f"/api/kanban/{kid}/move", {"direction": "next"})
    t("Kanban delete", "DELETE", f"/api/kanban/{kid}")

# DELIVERY
t("Delivery overview", "GET", "/api/delivery/overview", check=lambda d: "active_projects" in d)
t(
    "Delivery templates",
    "GET",
    "/api/delivery/templates",
    check=lambda d: isinstance(d, dict)
    and isinstance(d.get("templates"), list)
    and len(d.get("templates") or []) >= 5,
)
rdp = t(
    "Delivery create project",
    "POST",
    "/api/delivery/projects",
    {"name": "QA_DP", "type": "Лендинг"},
    check=lambda d: "id" in d,
)
dpid = rdp.json().get("id") if rdp and rdp.status_code == 200 else None
if dpid:
    t("Delivery update project", "PUT", f"/api/delivery/projects/{dpid}", {"status": "В работе"})
    rs = t(
        "Delivery create stage",
        "POST",
        f"/api/delivery/projects/{dpid}/stages",
        {"name": "QA_STAGE"},
        check=lambda d: "id" in d,
    )
    sid = rs.json().get("id") if rs and rs.status_code == 200 else None
    rdt = t(
        "Delivery create task",
        "POST",
        "/api/delivery/tasks",
        {"project_id": dpid, "stage_id": sid, "title": "QA_DTASK"},
        check=lambda d: "id" in d,
    )
    dtid = rdt.json().get("id") if rdt and rdt.status_code == 200 else None
    if dtid:
        t("Delivery update task", "PUT", f"/api/delivery/tasks/{dtid}", {"status": "In Progress"})
        t(
            "Delivery task GET",
            "GET",
            f"/api/delivery/tasks/{dtid}",
            check=lambda d: "checklist" in d,
        )
        t("Delivery add comment", "POST", f"/api/delivery/tasks/{dtid}/comments", {"body": "test"})
        t("Delivery delete task", "DELETE", f"/api/delivery/tasks/{dtid}")
    if sid:
        t("Delivery delete stage", "DELETE", f"/api/delivery/stages/{sid}")
    t("Delivery delete project", "DELETE", f"/api/delivery/projects/{dpid}")

# SEARCH
t("Search works", "GET", "/api/search?q=test", check=lambda d: isinstance(d, list))
t("Search short empty", "GET", "/api/search?q=a", check=lambda d: d == [])

# EXECUTORS
t(
    "Executors list",
    "GET",
    "/api/delivery/executors",
    check=lambda d: isinstance(d, dict) and isinstance(d.get("executors"), list),
)
re = httpx.get(f"{BASE}/api/delivery/executors", headers=H, timeout=10)
if re.status_code == 200:
    exe = re.json().get("executors") if isinstance(re.json(), dict) else []
    if exe:
        eid = exe[0]["id"]
        t(
            "Executors tasks",
            "GET",
            f"/api/delivery/executors/{eid}/tasks",
            check=lambda d: "delivery_tasks" in d,
        )

# KNOWLEDGE
t(
    "Knowledge list",
    "GET",
    "/api/knowledge",
    check=lambda d: isinstance(d, dict) and isinstance(d.get("files"), list),
)

# ANALYTICS
t("Analytics overview", "GET", "/api/analytics/overview")

# STUDENTS
t(
    "Students list",
    "GET",
    "/api/students",
    check=lambda d: isinstance(d, dict) and isinstance(d.get("students"), list),
)

# CLEANUP
if cid:
    httpx.delete(f"{BASE}/api/clients/{cid}", headers=H, timeout=10)
if pid:
    httpx.delete(f"{BASE}/api/projects/{pid}", headers=H, timeout=10)

print("\n".join(passed))
if failed:
    print("\n--- FAILED ---")
    for fline in failed:
        print(fline)
total = len(passed) + len(failed)
print(f"\nRESULT: {len(passed)}/{total}")
sys.exit(0 if not failed else 1)
