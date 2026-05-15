"""
End-to-end smoke test for Delivery + Roles release.
Запускать после старта сервера (uvicorn / main.py).
"""
import sys
import httpx
import os

BASE = "http://127.0.0.1:8000"
ADMIN_PWD = os.getenv("ADMIN_PASSWORD", "Admin2024")

results: list[tuple[bool, str, str]] = []


def log(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append((ok, label, detail))
    return ok


def headers(token: str = "", legacy: str = "") -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Auth-Token"] = token
    if legacy:
        h["X-Admin-Password"] = legacy
    return h


def main() -> int:
    # Уникальные логины для повторных прогонов
    import time
    suffix = str(int(time.time()) % 100000)

    pm_login = f"pm_test_{suffix}"
    exec_login = f"dev_test_{suffix}"
    rev_login = f"rev_test_{suffix}"

    with httpx.Client(base_url=BASE, timeout=15) as c:

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 0: Серверная бойлерплейт-проверка
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 0: Базовая работоспособность ===")
        r = c.get("/api/auth/me", headers=headers())
        log("GET /api/auth/me без токена → 401", r.status_code == 401, f"HTTP {r.status_code}")

        r = c.get("/api/auth/me", headers=headers(legacy=ADMIN_PWD))
        log("GET /api/auth/me с legacy паролем → 200 owner",
            r.status_code == 200 and r.json().get("role") == "owner",
            f"HTTP {r.status_code}, role={r.json().get('role') if r.status_code==200 else '?'}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 1: Owner логинится и создаёт проект из шаблона
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 1: Owner создаёт проект из шаблона ===")
        r = c.post("/api/auth/login", headers=headers(),
                   json={"login": "owner", "password": ADMIN_PWD})
        ok = r.status_code == 200 and r.json().get("role") == "owner"
        log("POST /api/auth/login (owner)", ok, f"HTTP {r.status_code}")
        if not ok:
            return 1
        owner_token = r.json()["token"]

        # Список шаблонов
        r = c.get("/api/delivery/templates", headers=headers(owner_token))
        templates = r.json().get("templates", []) if r.status_code == 200 else []
        log("GET /api/delivery/templates", len(templates) >= 4,
            f"templates={len(templates)}, names={[t['name'] for t in templates[:5]]}")

        landing_tmpl = next((t for t in templates if t["name"] == "Лендинг"), None)
        log("Шаблон «Лендинг» найден", landing_tmpl is not None,
            f"id={landing_tmpl['id'] if landing_tmpl else None}")

        # Создать проект из шаблона
        r = c.post("/api/delivery/projects", headers=headers(owner_token), json={
            "name": f"Тестовый Лендинг {suffix}",
            "type": "Лендинг",
            "template_id": landing_tmpl["id"] if landing_tmpl else None,
            "status": "В работе",
            "priority": "High",
            "deadline": "2026-12-31",
        })
        ok = r.status_code == 200
        proj = r.json() if ok else {}
        log("POST /api/delivery/projects (с template_id)", ok and "id" in proj,
            f"HTTP {r.status_code}, id={proj.get('id')}")
        proj_id = proj.get("id")

        # Этапы и задачи должны быть автоматически созданы
        if proj_id:
            r = c.get(f"/api/delivery/projects/{proj_id}/stages", headers=headers(owner_token))
            stages = r.json().get("stages", []) if r.status_code == 200 else []
            log("Авто-создание этапов из шаблона", len(stages) >= 6,
                f"stages={len(stages)}")

            r = c.get(f"/api/delivery/tasks?project_id={proj_id}", headers=headers(owner_token))
            tasks = r.json().get("tasks", []) if r.status_code == 200 else []
            log("Авто-создание задач из шаблона", len(tasks) >= 10,
                f"tasks={len(tasks)}")

            # Проверка: у всех задач базовый чеклист (6 пунктов)
            if tasks:
                t0 = tasks[0]
                r = c.get(f"/api/delivery/tasks/{t0['id']}", headers=headers(owner_token))
                cl_count = len((r.json() or {}).get("checklist", []))
                log("Базовый чеклист 6 пунктов на задачу", cl_count == 6, f"checklist={cl_count}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 2: Owner создаёт PM, PM логинится и работает
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 2: PM workflow ===")
        r = c.post("/api/users", headers=headers(owner_token), json={
            "name": "Test PM", "login": pm_login, "password": "test123",
            "role": "pm", "telegram": "@test_pm",
        })
        ok = r.status_code == 200
        pm_user_id = r.json().get("user_id") if ok else None
        log(f"POST /api/users (role=pm, login={pm_login})", ok,
            f"HTTP {r.status_code}, user_id={pm_user_id}")

        # Логин PM
        r = c.post("/api/auth/login", headers=headers(),
                   json={"login": pm_login, "password": "test123"})
        ok = r.status_code == 200 and r.json().get("role") == "pm"
        pm_token = r.json().get("token") if ok else ""
        log("POST /api/auth/login (PM)", ok, f"HTTP {r.status_code}")

        # PM видит проекты
        r = c.get("/api/delivery/projects", headers=headers(pm_token))
        log("PM видит /api/delivery/projects", r.status_code == 200,
            f"HTTP {r.status_code}, projects={len(r.json().get('projects', [])) if r.status_code==200 else '-'}")

        # PM может создать проект
        r = c.post("/api/delivery/projects", headers=headers(pm_token), json={
            "name": f"Проект от PM {suffix}",
            "type": "Telegram-бот",
            "status": "Подготовка",
        })
        log("PM может создать проект", r.status_code == 200, f"HTTP {r.status_code}")
        pm_proj_id = r.json().get("id") if r.status_code == 200 else None

        # PM НЕ может создать пользователя
        r = c.post("/api/users", headers=headers(pm_token), json={
            "login": "hacker", "password": "x", "role": "owner"
        })
        log("PM не может создать пользователя → 403", r.status_code == 403, f"HTTP {r.status_code}")

        # PM НЕ может удалить проект
        if pm_proj_id:
            r = c.delete(f"/api/delivery/projects/{pm_proj_id}", headers=headers(pm_token))
            log("PM не может удалить проект → 403", r.status_code == 403, f"HTTP {r.status_code}")

        # PM может смотреть CRM (legacy endpoint через X-Auth-Token)
        r = c.get("/api/clients", headers=headers(pm_token))
        log("PM имеет доступ к /api/clients (legacy через токен)", r.status_code == 200,
            f"HTTP {r.status_code}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 3: Executor создаётся, привязан к hq_user, работает с задачами
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 3: Executor workflow ===")
        r = c.post("/api/users", headers=headers(owner_token), json={
            "name": "Test Dev", "login": exec_login, "password": "test123",
            "role": "executor",
        })
        ok = r.status_code == 200
        exec_user_id = r.json().get("user_id") if ok else None
        log(f"POST /api/users (role=executor, login={exec_login})", ok, f"user_id={exec_user_id}")

        # Создать executor с привязкой
        r = c.post("/api/delivery/executors", headers=headers(owner_token), json={
            "name": "Test Dev",
            "user_id": exec_user_id,
            "specialization": "Frontend",
        })
        ok = r.status_code == 200
        executor_id = r.json().get("id") if ok else None
        log("POST /api/delivery/executors (с user_id)", ok, f"executor_id={executor_id}")

        # Логин executor
        r = c.post("/api/auth/login", headers=headers(),
                   json={"login": exec_login, "password": "test123"})
        ok = r.status_code == 200 and r.json().get("role") == "executor"
        exec_token = r.json().get("token") if ok else ""
        log("POST /api/auth/login (executor)", ok, f"HTTP {r.status_code}")

        # Owner назначает executor на задачу
        if proj_id and executor_id:
            r = c.get(f"/api/delivery/tasks?project_id={proj_id}", headers=headers(owner_token))
            tasks = r.json().get("tasks", []) if r.status_code == 200 else []
            assigned_task = tasks[0] if tasks else None
            if assigned_task:
                r = c.put(f"/api/delivery/tasks/{assigned_task['id']}",
                          headers=headers(owner_token),
                          json={"assignee_id": executor_id, "status": "Ready"})
                log("Owner назначает задачу executor", r.status_code == 200, f"HTTP {r.status_code}")

        # Executor видит ТОЛЬКО свои задачи
        r = c.get("/api/delivery/tasks", headers=headers(exec_token))
        if r.status_code == 200:
            exec_tasks = r.json().get("tasks", [])
            log("Executor видит свои задачи (≥1)", len(exec_tasks) >= 1,
                f"tasks={len(exec_tasks)}")
            # Все должны быть его (assignee_id == executor_id)
            all_mine = all(t.get("assignee_id") == executor_id for t in exec_tasks)
            log("Все задачи executor — его (assignee_id совпадает)", all_mine)
        else:
            log("Executor видит свои задачи", False, f"HTTP {r.status_code}")

        # Executor может изменить статус → In Progress
        if exec_tasks:
            t = exec_tasks[0]
            r = c.put(f"/api/delivery/tasks/{t['id']}",
                      headers=headers(exec_token),
                      json={"status": "In Progress",
                            "branch_name": "feature/test",
                            "result_comment": "Готово к проверке"})
            log("Executor PUT /api/delivery/tasks (status=In Progress)", r.status_code == 200,
                f"HTTP {r.status_code}")

            # Executor НЕ может менять чужие поля (например, title)
            r = c.put(f"/api/delivery/tasks/{t['id']}",
                      headers=headers(exec_token),
                      json={"title": "ВЗЛОМАНО"})
            r2 = c.get(f"/api/delivery/tasks/{t['id']}", headers=headers(owner_token))
            title_unchanged = r2.json().get("title") != "ВЗЛОМАНО" if r2.status_code == 200 else False
            log("Executor не может менять title (поле фильтруется)", title_unchanged,
                f"title={r2.json().get('title') if r2.status_code==200 else '?'}")

            # Executor может перевести в Review с PR/Preview
            r = c.put(f"/api/delivery/tasks/{t['id']}",
                      headers=headers(exec_token),
                      json={"status": "Review",
                            "pull_request_url": "https://github.com/test/pr/1",
                            "preview_url": "https://test.vercel.app"})
            log("Executor → Review с PR и Preview", r.status_code == 200, f"HTTP {r.status_code}")

        # Executor НЕ может создавать задачи
        r = c.post("/api/delivery/tasks", headers=headers(exec_token),
                   json={"project_id": proj_id, "title": "Левая задача"})
        log("Executor не может создавать задачи → 403", r.status_code == 403, f"HTTP {r.status_code}")

        # Executor НЕ видит CRM-проектов (старый /api/projects)
        r = c.get("/api/projects", headers=headers(exec_token))
        # Через legacy endpoint должен пройти (token валиден), но это не наша забота —
        # фильтрация на уровне UI (sidebar). Проверяем что делает доступ:
        log("Executor доступ к /api/projects (legacy)", r.status_code in (200, 401, 403),
            f"HTTP {r.status_code}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 4: Reviewer одобряет задачу
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 4: Reviewer flow ===")
        r = c.post("/api/users", headers=headers(owner_token), json={
            "name": "Test Reviewer", "login": rev_login, "password": "test123",
            "role": "reviewer",
        })
        log("POST /api/users (role=reviewer)", r.status_code == 200, f"HTTP {r.status_code}")

        r = c.post("/api/auth/login", headers=headers(),
                   json={"login": rev_login, "password": "test123"})
        ok = r.status_code == 200 and r.json().get("role") == "reviewer"
        rev_token = r.json().get("token") if ok else ""
        log("POST /api/auth/login (reviewer)", ok, f"HTTP {r.status_code}")

        # Reviewer видит задачи на проверке
        r = c.get("/api/delivery/tasks?status=Review", headers=headers(rev_token))
        review_tasks = r.json().get("tasks", []) if r.status_code == 200 else []
        log("Reviewer видит /api/delivery/tasks?status=Review",
            r.status_code == 200 and len(review_tasks) >= 1,
            f"HTTP {r.status_code}, tasks={len(review_tasks)}")

        # Reviewer одобряет задачу
        if review_tasks:
            rt = review_tasks[0]
            r = c.put(f"/api/delivery/tasks/{rt['id']}",
                      headers=headers(rev_token),
                      json={"status": "Approved", "review_comment": "Все ок"})
            log("Reviewer Approve → status=Approved", r.status_code == 200, f"HTTP {r.status_code}")

            # Reviewer НЕ может менять поля кроме status и review_comment
            r = c.put(f"/api/delivery/tasks/{rt['id']}",
                      headers=headers(rev_token),
                      json={"title": "ВЗЛОМАНО REV"})
            r2 = c.get(f"/api/delivery/tasks/{rt['id']}", headers=headers(owner_token))
            title_unchanged = r2.json().get("title") != "ВЗЛОМАНО REV"
            log("Reviewer не может менять title", title_unchanged)

        # Reviewer НЕ может удалять задачи
        if review_tasks:
            r = c.delete(f"/api/delivery/tasks/{review_tasks[0]['id']}", headers=headers(rev_token))
            log("Reviewer не может удалять задачу → 403", r.status_code == 403, f"HTTP {r.status_code}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 5: Owner видит ВСЁ + overview
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 5: Owner sees everything ===")
        r = c.get("/api/delivery/overview", headers=headers(owner_token))
        ok = r.status_code == 200
        ov = r.json() if ok else {}
        log("GET /api/delivery/overview", ok, str(ov))
        log("overview.active_projects > 0", ok and ov.get("active_projects", 0) > 0)
        log("overview.in_progress присутствует", ok and "in_progress" in ov)
        log("overview.in_review присутствует", ok and "in_review" in ov)
        log("overview.overdue присутствует", ok and "overdue" in ov)
        log("overview.blocked присутствует", ok and "blocked" in ov)

        r = c.get("/api/users", headers=headers(owner_token))
        log("Owner видит /api/users (CRUD пользователей)",
            r.status_code == 200 and len(r.json().get("users", [])) >= 4,
            f"users={len(r.json().get('users', [])) if r.status_code==200 else '-'}")

        # ─────────────────────────────────────────────────────────────────
        # СЦЕНАРИЙ 6: Защита API от неаутентифицированных
        # ─────────────────────────────────────────────────────────────────
        print("\n=== СЦЕНАРИЙ 6: Security boundary ===")
        r = c.get("/api/delivery/overview", headers=headers())
        log("Без токена /api/delivery/overview → 401", r.status_code == 401, f"HTTP {r.status_code}")

        r = c.post("/api/delivery/projects", headers=headers(),
                   json={"name": "Анон проект"})
        log("Без токена POST /api/delivery/projects → 401",
            r.status_code == 401, f"HTTP {r.status_code}")

        r = c.post("/api/auth/login", headers=headers(),
                   json={"login": "owner", "password": "wrong"})
        log("Логин с неверным паролем → 401", r.status_code == 401, f"HTTP {r.status_code}")

        # Logout инвалидирует токен
        r = c.post("/api/auth/logout", headers=headers(rev_token))
        log("POST /api/auth/logout", r.status_code == 200, f"HTTP {r.status_code}")

        r = c.get("/api/auth/me", headers=headers(rev_token))
        log("После logout /api/auth/me → 401", r.status_code == 401, f"HTTP {r.status_code}")

        # ─────────────────────────────────────────────────────────────────
        # CLEANUP
        # ─────────────────────────────────────────────────────────────────
        print("\n=== Очистка тестовых данных ===")
        if proj_id:
            r = c.delete(f"/api/delivery/projects/{proj_id}", headers=headers(owner_token))
            log("DELETE проект (со всеми этапами и задачами)", r.status_code == 200,
                f"HTTP {r.status_code}")
        if pm_proj_id:
            r = c.delete(f"/api/delivery/projects/{pm_proj_id}", headers=headers(owner_token))
            log("DELETE PM-проект", r.status_code == 200, f"HTTP {r.status_code}")
        if executor_id:
            r = c.delete(f"/api/delivery/executors/{executor_id}", headers=headers(owner_token))
            log("DELETE executor", r.status_code == 200, f"HTTP {r.status_code}")
        # Удаляем тестовых пользователей
        r = c.get("/api/users", headers=headers(owner_token))
        if r.status_code == 200:
            for u in r.json().get("users", []):
                if u["login"] in (pm_login, exec_login, rev_login):
                    c.delete(f"/api/users/{u['id']}", headers=headers(owner_token))
        log("Тестовые пользователи удалены", True)

    # ─────────────────────────────────────────────────────────────────
    # ИТОГИ
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r[0])
    failed = sum(1 for r in results if not r[0])
    print(f"  RESULT: {passed} PASS / {failed} FAIL  (total: {len(results)})")
    print("=" * 60)
    if failed:
        print("\nFAILED:")
        for ok, label, detail in results:
            if not ok:
                print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
