"""
Проверка 4 спринтов (контракты API соответствуют фактической реализации HQ).
Запуск: из каталога ai_agency — python tools/sprint5_verify.py [--db-only]

По умолчанию пробует HTTP (SPRINT5_BASE). Если сервер недоступен — ASGI (FastAPI в процессе),
если не задано SPRINT5_HTTP=1.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import aiosqlite
import httpx

# корень ai_agency (родитель tools/)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import DB_PATH, init_db  # noqa: E402

BASE = os.environ.get("SPRINT5_BASE", "http://127.0.0.1:8000")
PW = os.environ.get("ADMIN_PASSWORD", "Admin2024")
HEADERS = {"X-Admin-Password": PW, "Content-Type": "application/json"}


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _server_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE}/api/dashboard/stats", headers=HEADERS, timeout=2.5)
        return r.status_code in (200, 401, 403)
    except Exception:
        return False


async def check_db_schema() -> bool:
    """Фаза 2: таблицы и PRAGMA. True = есть критические [!!]."""
    dbp = str(DB_PATH)
    if not Path(dbp).exists():
        print(f"[!] DB {dbp} missing -> init_db()...")
        await init_db()
    results: list[str] = []

    async with aiosqlite.connect(dbp) as db:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in await cur.fetchall()]

        def has_t(n: str) -> bool:
            ok = n in tables
            results.append(f"{'[OK]' if ok else '[!!]'} таблица {n}")
            return ok

        has_t("tasks_v2_checklist")
        has_t("tasks_v2_comments")
        has_t("hq_users")
        has_t("student_projects")
        has_t("student_expenses")
        has_t("delivery_projects")
        has_t("delivery_templates")

        checks = [
            ("tasks_v2", "assignee_id"),
            ("students", "revenue_type"),
            ("students", "student_total"),
            ("students", "student_paid"),
            ("students", "student_percent"),
            ("students", "expense_total"),
            ("students", "expense_paid"),
            ("students", "notes"),
            ("students", "source"),
            ("delivery_projects", "student_id"),
            ("delivery_projects", "owner_type"),
            ("delivery_projects", "our_percent"),
            ("delivery_projects", "our_amount"),
            ("executors", "level"),
            ("delivery_templates", "estimated_days"),
            ("delivery_templates", "icon"),
        ]
        for table, col in checks:
            if table not in tables:
                results.append(f"[!!] PRAGMA skip {table}.{col} (no table)")
                continue
            cur = await db.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in await cur.fetchall()]
            ok = col in cols
            results.append(f"{'[OK]' if ok else '[!!]'} {table}.{col}")

        cur = await db.execute("SELECT COUNT(*) FROM delivery_templates")
        tmpl_count = int((await cur.fetchone())[0])
        results.append(
            f"{'[OK]' if tmpl_count >= 8 else '[--]'} delivery_templates count: {tmpl_count} (need >=8)"
        )

        cur = await db.execute("SELECT id FROM hq_users WHERE login='owner' LIMIT 1")
        owner = await cur.fetchone()
        results.append(f"{'[OK]' if owner else '[!!]'} hq_users login=owner")

    for r in results:
        print(r)
    return any(x.startswith("[!!]") for x in results)


async def repair_db_schema_if_needed() -> None:
    bad = await check_db_schema()
    if bad:
        print("[!] DB schema issues -> init_db()...")
        await init_db()
        print("[.] Re-check after init_db:")
        await check_db_schema()


async def run_api_and_smoke(client: httpx.AsyncClient, app_for_perm) -> tuple[int, int, int, int]:
    """Возвращает (ok_count, fail_count, smoke_ok, smoke_total)."""
    ok_l: list[str] = []
    fail_l: list[str] = []

    async def check(
        _name: str,
        method: str,
        url: str,
        body=None,
        expect=200,
        check_fn=None,
    ):
        try:
            kw: dict = {}
            if body is not None:
                kw["json"] = body
            r = await client.request(method, url, **kw)
            ok = r.status_code == expect
            if ok and check_fn:
                try:
                    ok = bool(check_fn(r.json()))
                except Exception:
                    ok = False
            line = f"{'[OK]' if ok else '[!!]'} [{method}] {url}"
            if not ok:
                line += f" -> {r.status_code}: {(r.text or '')[:120]}"
            (ok_l if ok else fail_l).append(line)
            return r
        except Exception as e:
            fail_l.append(f"[!!] [{method}] {url} -> ERROR: {e}")
            return None

    r = await check(
        "Auth login",
        "POST",
        "/api/auth/login",
        {"login": "owner", "password": PW},
        check_fn=lambda d: "token" in d,
    )
    token = r.json().get("token", "") if r and r.status_code == 200 else ""
    if token:
        client.headers["X-Auth-Token"] = token

    h_token = {**HEADERS, "X-Auth-Token": token} if token else dict(HEADERS)
    try:
        rr = await client.get("/api/auth/me", headers=h_token)
        auth_ok = rr.status_code == 200
        (ok_l if auth_ok else fail_l).append(
            f"{'[OK]' if auth_ok else '[!!]'} [GET] /api/auth/me (token)"
        )
    except Exception as e:
        fail_l.append(f"[!!] [GET] /api/auth/me -> {e}")

    await check(
        "Dashboard stats",
        "GET",
        "/api/dashboard/stats",
        check_fn=lambda d: "expected_payments" in d and "active_clients" in d,
    )
    await check(
        "Dashboard agency_expected",
        "GET",
        "/api/dashboard/stats",
        check_fn=lambda d: "agency_expected" in d,
    )
    await check(
        "Dashboard student_expected",
        "GET",
        "/api/dashboard/stats",
        check_fn=lambda d: "student_expected" in d,
    )

    rt = await check("Tasks create", "POST", "/api/tasks-v2", {"title": "VERIFY_TEST_TASK"})
    tid = rt.json().get("id") if rt and rt.status_code in (200, 201) else None

    if tid:
        await check(
            "Tasks GET checklist+comments",
            "GET",
            f"/api/tasks-v2/{tid}",
            check_fn=lambda d: "checklist" in d and "comments" in d,
        )
        rc = await check(
            "Tasks checklist add",
            "POST",
            f"/api/tasks-v2/{tid}/checklist",
            {"title": "test item"},
        )
        iid = rc.json().get("id") if rc and rc.status_code in (200, 201) else None
        if iid:
            await check(
                "Tasks checklist toggle",
                "PUT",
                f"/api/tasks-v2/checklist/{iid}",
                {"is_completed": True},
            )
            await check("Tasks checklist delete", "DELETE", f"/api/tasks-v2/checklist/{iid}")

        await check(
            "Tasks comment add",
            "POST",
            f"/api/tasks-v2/{tid}/comments",
            {"body": "test comment"},
        )
        await check("Tasks metrics", "GET", "/api/tasks-v2/metrics", check_fn=lambda d: "open" in d)
        await check("Tasks delete", "DELETE", f"/api/tasks-v2/{tid}")

    await check(
        "Students list",
        "GET",
        "/api/students",
        check_fn=lambda d: isinstance(d.get("students"), list),
    )
    await check(
        "Students fields",
        "GET",
        "/api/students",
        check_fn=lambda d: len(d.get("students") or []) == 0
        or "revenue_type" in d["students"][0],
    )
    await check(
        "Students summary",
        "GET",
        "/api/students/summary",
        check_fn=lambda d: "income" in d and "expenses" in d,
    )

    rs = await check(
        "Students create extended",
        "POST",
        "/api/students",
        {
            "name": "VERIFY_TEST_STUDENT",
            "student_total": 50000,
            "student_paid": 10000,
            "revenue_type": "student",
        },
    )
    sid = rs.json().get("id") if rs and rs.status_code in (200, 201) else None

    if sid:
        rsp = await check(
            "Student project create",
            "POST",
            f"/api/students/{sid}/projects",
            {"name": "Test Project", "total_amount": 100000, "our_percent": 20},
        )
        spid = rsp.json().get("id") if rsp and rsp.status_code in (200, 201) else None
        if spid:
            await check(
                "Student project our_amount",
                "GET",
                f"/api/students/{sid}",
                check_fn=lambda d: any(
                    float(p.get("our_amount") or 0) == 20000.0 for p in d.get("projects", [])
                ),
            )
            await check("Student project delete", "DELETE", f"/api/students/projects/{spid}")

        rse = await check(
            "Student expense create",
            "POST",
            f"/api/students/{sid}/expenses",
            {"description": "Test expense", "amount": 5000},
        )
        seid = rse.json().get("id") if rse and rse.status_code in (200, 201) else None
        if seid:
            await check("Student expense PUT", "PUT", f"/api/students/expenses/{seid}", {"paid": 1})
            await check("Student expense delete", "DELETE", f"/api/students/expenses/{seid}")

        await check("Student delete", "DELETE", f"/api/students/{sid}")

    await check(
        "Delivery projects",
        "GET",
        "/api/delivery/projects",
        check_fn=lambda d: isinstance(d.get("projects"), list),
    )
    await check(
        "Delivery overview",
        "GET",
        "/api/delivery/overview",
        check_fn=lambda d: "active_projects" in d,
    )
    await check(
        "Delivery templates",
        "GET",
        "/api/delivery/templates",
        check_fn=lambda d: isinstance(d.get("templates"), list)
        and len(d.get("templates") or []) >= 8,
    )

    rdp = await check(
        "Delivery student project",
        "POST",
        "/api/delivery/projects",
        {
            "name": "VERIFY_STUDENT_PROJECT",
            "owner_type": "student",
            "our_percent": 25,
            "budget": 80000,
        },
    )
    dpid = rdp.json().get("id") if rdp and rdp.status_code in (200, 201) else None
    if dpid:
        await check(
            "Delivery GET owner_type",
            "GET",
            f"/api/delivery/projects/{dpid}",
            check_fn=lambda d: d.get("owner_type") == "student"
            and abs(float(d.get("our_amount") or 0) - 20000.0) < 0.01,
        )
        await check("Delivery delete test", "DELETE", f"/api/delivery/projects/{dpid}")

    await check(
        "Delivery executors",
        "GET",
        "/api/delivery/executors",
        check_fn=lambda d: isinstance(d.get("executors"), list),
    )

    await check(
        "Finance summary",
        "GET",
        "/api/finance/summary",
        check_fn=lambda d: all(
            k in d for k in ["agency", "students", "total", "expenses", "percent"]
        ),
    )
    await check(
        "Finance agency keys",
        "GET",
        "/api/finance/summary",
        check_fn=lambda d: all(k in d.get("agency", {}) for k in ["received", "expected", "contracted"]),
    )
    await check(
        "Finance students keys",
        "GET",
        "/api/finance/summary",
        check_fn=lambda d: all(
            k in d.get("students", {}) for k in ["received", "expected", "contracted"]
        ),
    )
    await check(
        "Finance total net",
        "GET",
        "/api/finance/summary",
        check_fn=lambda d: "net" in d.get("total", {}),
    )

    try:
        transport = httpx.ASGITransport(app=app_for_perm)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://perm.local",
            headers={"Content-Type": "application/json"},
        ) as plain:
            nr = await plain.post("/api/clients", json={"name": "perm_test_no_auth"})
        perm_ok = nr.status_code == 401
        if not perm_ok and not os.getenv("ADMIN_PASSWORD"):
            perm_ok = nr.status_code in (200, 201)
            (ok_l if perm_ok else fail_l).append(
                "[OK] POST /api/clients без пароля — окно доступа "
                "(ADMIN_PASSWORD не задан, ожидание открытого режима)"
            )
        else:
            (ok_l if perm_ok else fail_l).append(
                f"{'[OK]' if perm_ok else '[!!]'} POST /api/clients no auth -> {nr.status_code}"
            )
    except Exception as e:
        fail_l.append(f"[!!] permissions test -> {e}")

    endpoints = [
        ("Dashboard stats", "/api/dashboard/stats"),
        ("Finance summary", "/api/finance/summary"),
        ("Clients", "/api/clients"),
        ("Projects", "/api/projects"),
        ("Students", "/api/students"),
        ("Students summary", "/api/students/summary"),
        ("Tasks v2", "/api/tasks-v2"),
        ("Tasks metrics", "/api/tasks-v2/metrics"),
        ("Delivery projects", "/api/delivery/projects"),
        ("Delivery overview", "/api/delivery/overview"),
        ("Delivery templates", "/api/delivery/templates"),
        ("Delivery executors", "/api/delivery/executors"),
        ("Knowledge", "/api/knowledge"),
        ("Analytics", "/api/analytics/overview"),
        ("Search", "/api/search?q=test"),
    ]
    smoke_ok = 0
    for name, url in endpoints:
        try:
            r = await client.get(url)
            ok = r.status_code == 200
            if ok:
                smoke_ok += 1
            print(f"{'[OK]' if ok else '[!!]'} smoke {name}: {r.status_code}")
        except Exception as e:
            print(f"[!!] smoke {name}: {e}")

    print("\n" + "=" * 50)
    print("DETAIL API")
    for x in ok_l:
        print(x)
    if fail_l:
        print("\n--- FAILED ---")
        for x in fail_l:
            print(x)
    total = len(ok_l) + len(fail_l)
    print("\n" + "=" * 50)
    print(f"API tests: {len(ok_l)}/{total} OK; smoke GET: {smoke_ok}/{len(endpoints)}")
    return len(ok_l), len(fail_l), smoke_ok, len(endpoints)


async def _run_api_phase() -> int:
    from api import app as fastapi_app  # noqa: WPS433

    force_http = _env_truthy("SPRINT5_HTTP")
    force_asgi = _env_truthy("SPRINT5_ASGI")
    use_asgi = force_asgi or (not force_http and not _server_reachable())
    fail_l = 0
    if use_asgi:
        print("[.] Mode: httpx.AsyncClient + ASGITransport (no live server)")
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=HEADERS,
            timeout=60.0,
        ) as client:
            _, fail_l, _, _ = await run_api_and_smoke(client, fastapi_app)
    else:
        print(f"[.] Mode: httpx.AsyncClient HTTP {BASE}")
        async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=30.0) as client:
            _, fail_l, _, _ = await run_api_and_smoke(client, fastapi_app)
    return 1 if fail_l else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-only", action="store_true", help="Only DB schema checks + repair")
    args = ap.parse_args()

    async def _main() -> int:
        await repair_db_schema_if_needed()
        if args.db_only:
            return 0
        return await _run_api_phase()

    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
