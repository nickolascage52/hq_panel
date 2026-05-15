"""
FastAPI приложение — REST API и WebSocket для управления AI-командой.

Глобальный поиск: маршрут GET "/api/search" регистрируется в hq_v3_api.py (функция v3_global_search).
"""

import os
import re
import asyncio
import json
import logging
import hashlib
import secrets
import aiosqlite
from pathlib import Path
from datetime import datetime, date, timedelta

import httpx

from fastapi import (
    FastAPI, HTTPException, WebSocket, WebSocketDisconnect,
    Depends, Query, Header, UploadFile, File, Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from database import (
    DB_PATH,
    init_db,
    backup_db,
    get_tasks, get_task, get_task_chain, get_content,
    get_content_by_id, update_content_status, get_metrics, create_task,
    get_clients, get_client, create_client, update_client, delete_client,
    archive_client, restore_client,
    get_projects, create_project, update_project, get_project_tasks,
    create_project_task, update_project_task, get_project,
    get_students, get_student, create_student, update_student,
    get_student_tasks, create_student_task, update_student_task,
    get_deadlines, get_daily_reports, save_daily_report, get_daily_report_by_id,
    get_business_metrics, count_tasks_due_today, add_hq_message, get_hq_messages,
    get_reminders_due, update_reminder_sent, create_reminder_row,
    get_metrics_cache_rows, upsert_metrics_cache,
    list_owner_notes, get_owner_note, create_owner_note, update_owner_note,
    delete_owner_note, owner_note_mark_sent_to_team,
    get_task_v2, sync_task_v2_ai_link, insert_timeline_event,
    create_student_progress_log, list_student_progress_logs,
)
from hq_v3_api import _sessions
from orchestrator import Orchestrator
from agency_context_loader import (
    get_context_meta, get_context_preview,
    save_uploaded_context, get_agency_context,
)
from hq_snapshot import build_account_snapshot_json
from agents.request_context import panel_model_override
from panel_settings import (
    get_resolved_hq_model_id,
    get_panel_settings_payload,
    save_panel_settings,
)

logger = logging.getLogger("api")

app = FastAPI(
    title="AI Agency Management System",
    description="API для управления AI-командой агентства",
    version="1.0.0",
)


@app.on_event("startup")
async def ensure_database_ready() -> None:
    """Гарантируем миграции и при запуске через `api:app`, и через `main.py`."""
    await init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def hq_trailing_slash_redirect(request: Request, call_next):
    """Без завершающего / браузер резолвит crm.html как /crm.html, а не /hq/crm.html."""
    if request.scope.get("type") == "http" and request.scope.get("path") == "/hq":
        return RedirectResponse(url="/hq/", status_code=307)
    return await call_next(request)


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

HQ_DIR = STATIC_DIR / "hq"
if HQ_DIR.is_dir():
    app.mount("/hq", StaticFiles(directory=str(HQ_DIR), html=True), name="hq")

# Маркетинговая страница «AI команда» — отдельно от панели: /service/
SERVICE_LANDING_DIR = STATIC_DIR / "site"
if SERVICE_LANDING_DIR.is_dir():
    app.mount(
        "/service",
        StaticFiles(directory=str(SERVICE_LANDING_DIR), html=True),
        name="service_landing",
    )


@app.get("/")
async def root_redirect_to_hq():
    """Главная → HQ (дашборд). Задачи агентам: /hq/team.html Лендинг: /service/"""
    return RedirectResponse(url="/hq/", status_code=302)


@app.get("/panel")
async def panel_alias():
    """Старый URL панели → AI Команда в HQ."""
    return RedirectResponse(url="/hq/team.html", status_code=302)


@app.get("/admin")
async def admin_legacy_redirect():
    """Старый Command Center убран; задачи и чат — в HQ → AI Команда."""
    return RedirectResponse(url="/hq/team.html", status_code=302)


orchestrator = Orchestrator()


# ── Аутентификация ──

def verify_password(
    password: str | None = Query(None, alias="password"),
    x_admin_password: str | None = Header(None, alias="X-Admin-Password"),
    x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
) -> bool:
    """Принимает либо старый ADMIN_PASSWORD, либо новый X-Auth-Token.

    Обратная совместимость: страницы со старым sessionStorage.hq_admin_password
    продолжают работать; новые страницы (PM/executor) шлют только токен.
    """
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    provided = x_admin_password or password
    # 1) Старый admin password
    if admin_pw and provided and provided == admin_pw:
        return True
    # 2) Новая сессия по токену
    if x_auth_token:
        sess = _sessions.get(x_auth_token)
        if sess and sess.get("expires") and sess["expires"] >= datetime.now():
            return True
    # 3) Если пароль не задан вообще — открытый доступ
    if not admin_pw:
        return True
    raise HTTPException(status_code=401, detail="Неверный пароль")


# ── Сессии и роли (новая система авторизации) ──
# Хранение в памяти достаточно для MVP: при рестарте все логинятся заново.
# dict _sessions объявлен в hq_v3_api.py (единый объект для api и v3-роутов).
_SESSION_TTL_DAYS = 7


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _resolve_session(request: Request) -> dict | None:
    """Вернуть активную сессию по X-Auth-Token (или None)."""
    token = request.headers.get("X-Auth-Token", "") or request.headers.get("x-auth-token", "")
    if not token:
        return None
    sess = _sessions.get(token)
    if not sess:
        return None
    if sess["expires"] < datetime.now():
        _sessions.pop(token, None)
        return None
    return sess


def require_role(*roles: str):
    """Зависимость FastAPI: требует роль из списка. Без аргументов — любая аутентифицированная.

    Обратная совместимость: запросы со старым X-Admin-Password считаются от owner.
    """

    async def checker(request: Request) -> dict:
        # 1) Старый пароль — auto-promote до owner
        old_pwd = request.headers.get("X-Admin-Password", "") or request.headers.get("x-admin-password", "")
        admin_pw = os.getenv("ADMIN_PASSWORD", "")
        if admin_pw and old_pwd and old_pwd == admin_pw:
            return {"user_id": 1, "role": "owner", "name": "Owner (legacy)"}

        # 2) Новая сессия по токену
        sess = _resolve_session(request)
        if not sess:
            raise HTTPException(status_code=401, detail="Не авторизован")
        if roles and sess["role"] not in roles:
            req = ", ".join(roles) if roles else ""
            raise HTTPException(
                status_code=403,
                detail=(
                    ("Недостаточно прав. Требуется: " + req) if req else "Недостаточно прав"
                ),
            )
        return sess

    return checker


def get_optional_hq_session(request: Request) -> dict | None:
    """Та же модель пользователя что в require_role, но без ошибки если нет авторизации."""

    old_pwd = (
        request.headers.get("X-Admin-Password", "")
        or request.headers.get("x-admin-password", "")
    )
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if admin_pw and old_pwd and old_pwd == admin_pw:
        return {"user_id": 1, "role": "owner", "name": "Owner (legacy)"}
    return _resolve_session(request)


# ── Эндпоинты аутентификации ──

@app.post("/api/auth/login")
async def auth_login(request: Request):
    """Аутентификация по логину и паролю. Возвращает токен сессии."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    login_str = (data.get("login") or "").strip()
    password = data.get("password") or ""
    if not login_str or not password:
        raise HTTPException(400, "Логин и пароль обязательны")
    pwd_hash = _sha256(password)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, login, role, status FROM hq_users "
            "WHERE login=? AND password_hash=?",
            (login_str, pwd_hash),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(401, "Неверный логин или пароль")
    user = dict(row)
    if (user.get("status") or "active") != "active":
        raise HTTPException(403, "Пользователь неактивен")
    token = secrets.token_hex(32)
    _sessions[token] = {
        "user_id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "expires": datetime.now() + timedelta(days=_SESSION_TTL_DAYS),
    }
    return {
        "token": token,
        "user_id": user["id"],
        "role": user["role"],
        "name": user["name"],
    }


@app.get("/api/auth/me")
async def auth_me(request: Request):
    """Вернуть данные текущего пользователя (или 401 если не авторизован)."""
    # Старый пароль → owner
    old_pwd = request.headers.get("X-Admin-Password", "")
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if admin_pw and old_pwd and old_pwd == admin_pw:
        return {"user_id": 1, "role": "owner", "name": "Owner"}
    sess = _resolve_session(request)
    if not sess:
        raise HTTPException(401, "Не авторизован")
    return {"user_id": sess["user_id"], "role": sess["role"], "name": sess["name"]}


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    """Удалить токен сессии."""
    token = request.headers.get("X-Auth-Token", "")
    _sessions.pop(token, None)
    return {"success": True}


# ── CRUD пользователей (только owner) ──

@app.get("/api/users")
async def api_users_list(_=Depends(require_role("owner", "pm"))):
    """Список всех пользователей HQ."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, login, role, telegram, email, github_username, "
            "specialization, status, created_at FROM hq_users ORDER BY created_at"
        )
        rows = await cur.fetchall()
    return {"users": [dict(r) for r in rows]}


@app.post("/api/users")
async def api_users_create(request: Request, _=Depends(require_role("owner"))):
    """Создать пользователя. Требуются login и password."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    login_str = (data.get("login") or "").strip()
    password = data.get("password") or ""
    if not login_str or not password:
        raise HTTPException(400, "Логин и пароль обязательны")
    role = (data.get("role") or "executor").strip()
    if role not in {"owner", "pm", "executor", "reviewer"}:
        raise HTTPException(400, "Недопустимая роль")
    pwd_hash = _sha256(password)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        try:
            cur = await db.execute(
                "INSERT INTO hq_users "
                "(name, login, password_hash, role, telegram, email, "
                " github_username, specialization, status) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    (data.get("name") or login_str).strip(),
                    login_str,
                    pwd_hash,
                    role,
                    (data.get("telegram") or "").strip(),
                    (data.get("email") or "").strip(),
                    (data.get("github_username") or "").strip(),
                    (data.get("specialization") or "").strip(),
                    (data.get("status") or "active").strip(),
                ),
            )
            await db.commit()
            uid = cur.lastrowid
        except aiosqlite.IntegrityError:
            raise HTTPException(400, "Логин уже занят")
    return {"success": True, "user_id": uid}


@app.put("/api/users/{uid}")
async def api_users_update(uid: int, request: Request, _=Depends(require_role("owner"))):
    """Обновить пользователя. Поле password — опционально (хешируется)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    allowed = ["name", "role", "telegram", "email", "github_username", "specialization", "status"]
    updates: dict = {k: data[k] for k in allowed if k in data}
    if "role" in updates and updates["role"] not in {"owner", "pm", "executor", "reviewer"}:
        raise HTTPException(400, "Недопустимая роль")
    if data.get("password"):
        updates["password_hash"] = _sha256(data["password"])
    if not updates:
        return {"success": True}
    set_sql = ", ".join(f"{k}=?" for k in updates.keys())
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE hq_users SET {set_sql} WHERE id=?",
            list(updates.values()) + [uid],
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/users/{uid}")
async def api_users_delete(uid: int, _=Depends(require_role("owner"))):
    """Удалить пользователя. Owner защищён от удаления."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute("SELECT role FROM hq_users WHERE id=?", (uid,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Пользователь не найден")
        if row[0] == "owner":
            raise HTTPException(400, "Нельзя удалить owner")
        await db.execute("DELETE FROM hq_users WHERE id=?", (uid,))
        await db.commit()
    return {"success": True}


async def _hq_llm_run(coro):
    """Все вызовы LLM из HQ используют модель из настроек панели."""
    mid = await get_resolved_hq_model_id()
    tok = panel_model_override.set(mid)
    try:
        return await coro
    finally:
        panel_model_override.reset(tok)


# ── Модели запросов ──

class TaskRequest(BaseModel):
    """Задача владельца. task_mode: lite | standard | full — переопределение; None = Chief + .env."""

    message: str
    password: str | None = None
    task_mode: str | None = None
    task_v2_id: int | None = None
    agent_name: str | None = None


class ContentRejectRequest(BaseModel):
    comment: str


class PanelSettingsUpdate(BaseModel):
    """Пресет модели для HQ. custom_model_id — при preset=custom."""

    preset: str
    custom_model_id: str | None = None


# ── Роуты ──

@app.post("/api/task")
async def create_new_task(req: TaskRequest, _session=Depends(require_role("owner", "pm"))):
    """Принять задачу от владельца и поставить в очередь."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    task_id = await create_task(req.message)
    agent_name = (req.agent_name or "chief_of_staff").strip().lower().replace("-", "_") or "chief_of_staff"
    user_message_id = await add_hq_message(agent_name, "user", req.message)
    if req.task_v2_id:
        await sync_task_v2_ai_link(
            req.task_v2_id,
            legacy_task_id=task_id,
            agent_name=agent_name,
            user_message_id=user_message_id,
            status="в работе",
        )
        await insert_timeline_event(
            "task",
            req.task_v2_id,
            "агент",
            "Задача отправлена в AI-команду",
            meta={"legacy_task_id": task_id, "agent_name": agent_name},
            created_by="owner",
        )

    hq_model = await get_resolved_hq_model_id()
    asyncio.create_task(
        _run_task_background(req.message, task_id, req.task_mode, hq_model, req.task_v2_id, agent_name)
    )

    return {
        "task_id": task_id,
        "status": "queued",
        "message": f"Задача #{task_id} принята. Команда работает.",
    }


async def _run_task_background(
    message: str,
    task_id: int,
    task_mode: str | None,
    hq_model: str,
    task_v2_id: int | None = None,
    agent_name: str = "chief_of_staff",
):
    """Фоновое выполнение задачи (модель зафиксирована на момент постановки в очередь)."""
    tok = panel_model_override.set(hq_model)
    try:
        await orchestrator.run_task(message, task_id, task_mode=task_mode)
        task_row = await get_task(task_id)
        if task_v2_id and task_row:
            result_text = (task_row.get("result") or task_row.get("error") or "").strip()
            assistant_message_id = None
            if result_text:
                assistant_message_id = await add_hq_message(agent_name, "assistant", result_text)
            await sync_task_v2_ai_link(
                task_v2_id,
                legacy_task_id=task_id,
                agent_name=agent_name,
                assistant_message_id=assistant_message_id,
                response_preview=result_text[:500] if result_text else "",
                status="готово" if task_row.get("status") == "done" else "в работе",
            )
            await insert_timeline_event(
                "task",
                task_v2_id,
                "агент",
                "Ответ AI-команды получен" if task_row.get("status") == "done" else "Задача ещё выполняется",
                result_text[:3000],
                {"legacy_task_id": task_id, "agent_name": agent_name},
                agent_name,
            )
    except Exception as e:
        logger.error("Фоновая задача #%d упала: %s", task_id, e, exc_info=True)
        if task_v2_id:
            await sync_task_v2_ai_link(
                task_v2_id,
                legacy_task_id=task_id,
                agent_name=agent_name,
                response_preview=str(e),
                status="в работе",
            )
    finally:
        panel_model_override.reset(tok)


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: int, _auth: bool = Depends(verify_password)):
    """Статус и результат задачи."""
    status = await orchestrator.get_task_status(task_id)
    if "error" in status and status["error"] == "Задача не найдена":
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return status


@app.get("/api/tasks")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _auth: bool = Depends(verify_password),
):
    """Список последних задач."""
    tasks = await get_tasks(limit=limit, offset=offset)
    return {"tasks": tasks, "limit": limit, "offset": offset}


@app.get("/api/tasks/{task_id}/messages")
async def api_task_messages(task_id: int, _auth: bool = Depends(verify_password)):
    """Цепочка выполнений агентов по задаче (для HQ / интеграций)."""
    row = await get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    chain = await get_task_chain(task_id)
    return {"task": row, "messages": chain}


@app.get("/api/content")
async def list_content(
    status: str | None = Query(None),
    channel: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth: bool = Depends(verify_password),
):
    """Список контента с фильтрами."""
    content = await get_content(status=status, channel=channel, limit=limit)
    return {"content": content, "total": len(content)}


@app.get("/api/metrics")
async def system_metrics(_auth: bool = Depends(verify_password)):
    """Метрики системы."""
    metrics = await get_metrics()
    return metrics


@app.get("/api/panel/settings")
async def api_panel_settings_get(_auth: bool = Depends(verify_password)):
    """Настройки HQ: пресеты модели Claude (стоимость / качество)."""
    return await get_panel_settings_payload()


@app.put("/api/panel/settings")
async def api_panel_settings_put(
    body: PanelSettingsUpdate,
    _auth: bool = Depends(verify_password),
):
    try:
        return await save_panel_settings(body.preset, body.custom_model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/status")
async def system_status(_auth: bool = Depends(verify_password)):
    """Общий статус системы."""
    metrics = await get_metrics()
    team = orchestrator.team.list_agents()
    return {
        "status": "running",
        "agents_count": len(team),
        "agents": team,
        "active_tasks": len(orchestrator._active_tasks),
        "metrics": metrics,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/backup")
async def api_backup_db(
    tag: str = Query("manual", max_length=40),
    _auth: bool = Depends(verify_password),
):
    """Создать резервную копию БД."""
    try:
        dst = await backup_db(tag)
        return {"ok": True, "path": str(dst), "size_kb": round(dst.stat().st_size / 1024, 1)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка бэкапа: {e}")


@app.post("/api/content/{content_id}/approve")
async def approve_content(content_id: int, _auth: bool = Depends(verify_password)):
    """Одобрить контент."""
    content = await get_content_by_id(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Контент не найден")
    await update_content_status(content_id, "approved")
    return {"content_id": content_id, "status": "approved"}


@app.post("/api/content/{content_id}/reject")
async def reject_content(
    content_id: int,
    req: ContentRejectRequest,
    _auth: bool = Depends(verify_password),
):
    """Отклонить контент с комментарием."""
    content = await get_content_by_id(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Контент не найден")
    await update_content_status(content_id, "rejected", qa_notes=req.comment)
    return {"content_id": content_id, "status": "rejected", "comment": req.comment}


@app.post("/api/content/{content_id}/publish")
async def publish_content(content_id: int, _auth: bool = Depends(verify_password)):
    """Опубликовать контент в Telegram."""
    content = await get_content_by_id(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Контент не найден")

    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not channel_id or not bot_token:
        await update_content_status(content_id, "approved", qa_notes="Telegram не настроен")
        return {
            "content_id": content_id,
            "status": "approved",
            "message": "Telegram не настроен. Контент одобрен, но не опубликован.",
        }

    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": channel_id,
                "text": content["body"][:4096],
                "parse_mode": "HTML",
            }) as resp:
                result = await resp.json()
                if result.get("ok"):
                    await update_content_status(content_id, "published")
                    return {"content_id": content_id, "status": "published"}
                else:
                    error = result.get("description", "Неизвестная ошибка Telegram")
                    return {"content_id": content_id, "status": "error", "error": error}
    except Exception as e:
        logger.error("Ошибка публикации контента #%d: %s", content_id, e)
        return {"content_id": content_id, "status": "error", "error": str(e)}


# ── Контекст агентства ──

@app.get("/api/agency-context")
async def get_agency_context_status(_auth: bool = Depends(verify_password)):
    """Статус и превью текущего контекста агентства."""
    meta = get_context_meta()
    meta["content_preview"] = get_context_preview(300)
    return meta


@app.post("/api/agency-context/upload")
async def upload_agency_context(
    file: UploadFile = File(...),
    _auth: bool = Depends(verify_password),
):
    """Загрузить новый файл контекста агентства (.txt или .md, макс 500 КБ)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".txt", ".md"):
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый формат '{ext}'. Принимаются .txt и .md",
        )

    raw = await file.read()
    if len(raw) > 500 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой ({len(raw) // 1024} КБ). Максимум 500 КБ.",
        )

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Файл не в кодировке UTF-8. Пересохрани в UTF-8 и загрузи снова.",
        )

    result = save_uploaded_context(content, file.filename)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return {
        "success": True,
        "message": result["message"],
        "preview": result["preview"],
        "uploaded_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/agency-context/template")
async def download_context_template():
    """Скачать шаблон файла контекста агентства."""
    template = STATIC_DIR / "admin" / "agency_context_template.md"
    if not template.exists():
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return FileResponse(
        str(template),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="agency_context_template.md"'},
    )


# ── WebSocket для стриминга прогресса ──

@app.websocket("/ws/task/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: int):
    """Стриминг прогресса задачи в реальном времени."""
    await websocket.accept()

    try:
        progress = orchestrator.get_progress(task_id)
        if not progress:
            task = await get_task(task_id)
            if task:
                await websocket.send_json({
                    "stage": "done" if task["status"] == "done" else "info",
                    "message": f"Задача #{task_id} — статус: {task['status']}",
                    "result": task.get("result"),
                })
            else:
                await websocket.send_json({"stage": "error", "message": "Задача не найдена"})
            await websocket.close()
            return

        for step in progress.steps:
            await websocket.send_json(step)

        queue = progress.add_listener()
        try:
            while True:
                step = await queue.get()
                if step is None:
                    await websocket.send_json({"stage": "done", "message": "Задача завершена"})
                    break
                await websocket.send_json(step)
        finally:
            progress.remove_listener(queue)

    except WebSocketDisconnect:
        logger.info("WebSocket отключён для задачи #%d", task_id)
    except Exception as e:
        logger.error("Ошибка WebSocket задачи #%d: %s", task_id, e)
        try:
            await websocket.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# HQ — CRM, аккаунт-менеджер, чат с агентами, метрики
# ═══════════════════════════════════════════════════════════════════════════


async def _deterministic_today_items() -> list[dict]:
    """Напоминания дня без вызова LLM (дашборд / аккаунт)."""
    items: list[dict] = []
    today = date.today().isoformat()
    clients = await get_clients()
    for c in clients:
        nad = c.get("next_action_date")
        if not nad:
            continue
        if str(nad)[:10] != today:
            continue
        items.append({
            "type": "client",
            "icon": "👤",
            "title": c.get("name") or "Клиент",
            "detail": (c.get("next_action") or "Шаг по клиенту").strip(),
            "related_id": c["id"],
        })
    students = await get_students("active")
    for s in students:
        nsd = s.get("next_session_date")
        if nsd and str(nsd)[:10] == today:
            items.append({
                "type": "student",
                "icon": "🎓",
                "title": s.get("name") or "Ученик",
                "detail": f"Сессия сегодня · {s.get('program') or 'программа'}",
                "related_id": s["id"],
            })
    for r in await get_reminders_due(include_sent=False):
        if not r.get("scheduled_for"):
            continue
        if str(r["scheduled_for"])[:10] != today:
            continue
        items.append({
            "type": r.get("type") or "custom",
            "icon": "📌",
            "title": "Напоминание",
            "detail": r.get("text") or "",
            "related_id": r.get("related_id"),
            "reminder_id": r["id"],
        })
    dl = await get_deadlines(7)
    for d in dl:
        when = d.get("deadline") or d.get("due_date")
        if not when:
            continue
        if str(when)[:10] == today:
            label = d.get("name") or d.get("title") or "Дедлайн"
            items.append({
                "type": "deadline",
                "icon": "📅",
                "title": label,
                "detail": f"{d.get('type', '')} · {d.get('client_name') or ''}".strip(" ·"),
                "related_id": d.get("id"),
            })
    return items


def _deadline_row_urgency(due: str | None) -> str:
    if not due:
        return "ok"
    try:
        ds = str(due)[:10]
        d0 = date.fromisoformat(ds)
        today = date.today()
        delta = (d0 - today).days
        if delta < 0:
            return "overdue"
        if delta <= 1:
            return "soon"
        return "ok"
    except ValueError:
        return "ok"


class ClientCreateBody(BaseModel):
    name: str
    company: str | None = None
    contact: str | None = None
    service_type: str | None = "бот"
    status: str | None = "lead"
    start_date: str | None = None
    end_date: str | None = None
    total_amount: float | None = 0
    paid_amount: float | None = 0
    next_action: str | None = None
    next_action_date: str | None = None
    notes: str | None = None
    source: str | None = None


class ClientUpdateBody(BaseModel):
    name: str | None = None
    company: str | None = None
    contact: str | None = None
    service_type: str | None = None
    status: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    total_amount: float | None = None
    paid_amount: float | None = None
    next_action: str | None = None
    next_action_date: str | None = None
    notes: str | None = None
    source: str | None = None


class ProjectCreateBody(BaseModel):
    client_id: int | None = None
    name: str
    stage: str | None = "discovery"
    progress: int | None = 0
    description: str | None = None
    deadline: str | None = None
    executor: str | None = None
    budget: float | None = None
    priority: str | None = None
    notes: str | None = None


class ProjectUpdateBody(BaseModel):
    client_id: int | None = None
    name: str | None = None
    stage: str | None = None
    progress: int | None = None
    description: str | None = None
    deadline: str | None = None
    is_done: bool | None = None
    executor: str | None = None
    budget: float | None = None
    priority: str | None = None
    notes: str | None = None
    health_score: int | None = None


class ProjectTaskBody(BaseModel):
    title: str
    status: str | None = "todo"
    due_date: str | None = None


class ProjectTaskUpdateBody(BaseModel):
    title: str | None = None
    status: str | None = None
    due_date: str | None = None


class StudentCreateBody(BaseModel):
    name: str
    contact: str | None = None
    program: str | None = None
    start_date: str | None = None
    total_sessions: int | None = 0
    completed_sessions: int | None = 0
    payment_total: float | None = 0
    payment_received: float | None = 0
    next_session_date: str | None = None
    progress_notes: str | None = None
    status: str | None = "active"
    client_id: int | None = None
    revenue_type: str | None = None
    student_total: float | None = None
    student_paid: float | None = None
    student_percent: float | None = None
    expense_total: float | None = None
    expense_paid: float | None = None
    notes: str | None = None
    source: str | None = None


class StudentUpdateBody(BaseModel):
    name: str | None = None
    contact: str | None = None
    program: str | None = None
    start_date: str | None = None
    total_sessions: int | None = None
    completed_sessions: int | None = None
    payment_total: float | None = None
    payment_received: float | None = None
    next_session_date: str | None = None
    progress_notes: str | None = None
    status: str | None = None
    client_id: int | None = None
    revenue_type: str | None = None
    student_total: float | None = None
    student_paid: float | None = None
    student_percent: float | None = None
    expense_total: float | None = None
    expense_paid: float | None = None
    notes: str | None = None
    source: str | None = None


class StudentTaskBody(BaseModel):
    title: str
    description: str | None = None
    due_date: str | None = None
    status: str | None = "assigned"


class StudentTaskUpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    status: str | None = None
    feedback: str | None = None
    grade: int | None = None


class StudentQuickUpdateBody(BaseModel):
    action: str
    project_id: int | None = None
    note: str | None = None
    progress_delta: int | None = 0
    stage: str | None = None
    next_session_date: str | None = None


class AgentChatBody(BaseModel):
    message: str
    context: dict | None = None
    max_tokens: int | None = None


class AccountReportBody(BaseModel):
    save: bool = True
    prompt_extra: str | None = None


class AccountRemindBody(BaseModel):
    with_ai: bool = False


class ReminderUpdateBody(BaseModel):
    is_sent: int = 1


@app.get("/api/hq/dashboard-summary")
async def hq_dashboard_summary(_auth: bool = Depends(verify_password)):
    bm = await get_business_metrics()
    n_today = await count_tasks_due_today()
    recent = await get_tasks(limit=5, offset=0)
    projs = await get_projects()
    active = [dict(p) for p in projs if not p.get("is_done")]
    active.sort(key=lambda x: float(x.get("progress") or 0), reverse=True)
    return {
        "business": bm,
        "tasks_due_today_count": n_today,
        "recent_team_tasks": recent,
        "active_projects": active[:20],
        "today_items": await _deterministic_today_items(),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/clients")
async def api_list_clients(
    status: str | None = Query(None),
    include_archived: bool = Query(False),
    _auth: bool = Depends(verify_password),
):
    return {"clients": await get_clients(status, include_archived=include_archived)}


@app.post("/api/clients")
async def api_create_client(body: ClientCreateBody, _session=Depends(require_role("owner", "pm"))):
    cid = await create_client(body.model_dump(exclude_none=True))
    return {"id": cid}


@app.put("/api/clients/{client_id}")
async def api_update_client(
    client_id: int,
    body: ClientUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await update_client(client_id, data)
    if not ok and not data:
        raise HTTPException(status_code=400, detail="Нет полей для обновления")
    return {"ok": True}


@app.delete("/api/clients/{client_id}")
async def api_delete_client(client_id: int, _=Depends(require_role("owner"))):
    """Удаление клиента — только owner (P2-5: финансы и каскад)."""
    ok = await delete_client(client_id, cascade=True)
    if not ok:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return {"ok": True}


@app.post("/api/clients/{client_id}/archive")
async def api_archive_client(client_id: int, _session=Depends(require_role("owner", "pm"))):
    if not await get_client(client_id):
        raise HTTPException(status_code=404, detail="Клиент не найден")
    ok = await archive_client(client_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Клиент уже в архиве")
    return {"ok": True}


@app.post("/api/clients/{client_id}/restore")
async def api_restore_client(client_id: int, _session=Depends(require_role("owner", "pm"))):
    if not await get_client(client_id):
        raise HTTPException(status_code=404, detail="Клиент не найден")
    ok = await restore_client(client_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Клиент не в архиве")
    return {"ok": True}


@app.get("/api/clients/archived")
async def api_list_archived_clients(_auth: bool = Depends(verify_password)):
    all_clients = await get_clients(include_archived=True)
    archived = [c for c in all_clients if c.get("is_archived")]
    return {"clients": archived}


@app.get("/api/clients/{client_id}/projects")
async def api_client_projects(client_id: int, _auth: bool = Depends(verify_password)):
    if not await get_client(client_id):
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return {"projects": await get_projects(client_id)}


@app.get("/api/projects/{project_id}")
async def api_get_project_by_id(project_id: int, _auth: bool = Depends(verify_password)):
    row = await get_project(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return row


@app.get("/api/projects/{project_id}/tasks")
async def api_list_project_tasks(project_id: int, _auth: bool = Depends(verify_password)):
    if not await get_project(project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    return {"tasks": await get_project_tasks(project_id)}


@app.get("/api/projects")
async def api_all_projects(_auth: bool = Depends(verify_password)):
    return {"projects": await get_projects()}


@app.post("/api/projects")
async def api_create_project(body: ProjectCreateBody, _session=Depends(require_role("owner", "pm"))):
    if body.client_id is not None and not await get_client(body.client_id):
        raise HTTPException(status_code=404, detail="Клиент не найден")
    pid = await create_project(body.model_dump(exclude_none=True))
    proj = await get_project(pid)
    return proj if proj else {"id": pid}


@app.put("/api/projects/{project_id}")
async def api_update_project(
    project_id: int,
    body: ProjectUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = body.model_dump(exclude_unset=True)
    if "is_done" in data:
        data["is_done"] = 1 if data["is_done"] else 0
    ok = await update_project(project_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Проект не найден или нет изменений")
    return {"ok": True}


@app.post("/api/projects/{project_id}/tasks")
async def api_add_project_task(
    project_id: int,
    body: ProjectTaskBody,
    _session=Depends(require_role("owner", "pm")),
):
    if not await get_project(project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    tid = await create_project_task({
        "project_id": project_id,
        "title": body.title,
        "status": body.status or "todo",
        "due_date": body.due_date,
    })
    return {"id": tid}


@app.put("/api/tasks/{task_id}")
async def api_update_project_task_alias(
    task_id: int,
    body: ProjectTaskUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await update_project_task(task_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"ok": True}


@app.get("/api/students/summary")
async def api_students_summary(_session=Depends(require_role("owner"))):
    """Сводка по доходам с учеников, проектам учеников и расходам."""
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        income_cur = await db.execute(
            """
            SELECT
                COALESCE(SUM(student_paid), 0) AS total_received,
                COALESCE(SUM(COALESCE(student_total, 0) - COALESCE(student_paid, 0)), 0) AS total_expected,
                COALESCE(SUM(student_total), 0) AS total_contracted
            FROM students
            WHERE COALESCE(status, '') != 'archived'
            """
        )
        income_row = await income_cur.fetchone()

        proj_cur = await db.execute(
            """
            SELECT
                COALESCE(SUM(our_amount), 0) AS total_percent_amount,
                COALESCE(SUM(paid_amount), 0) AS total_percent_received
            FROM student_projects
            """
        )
        projects_row = await proj_cur.fetchone()

        exp_cur = await db.execute(
            """
            SELECT
                COALESCE(SUM(amount), 0) AS total_expenses,
                COALESCE(SUM(CASE WHEN paid=1 THEN amount ELSE 0 END), 0) AS paid_expenses
            FROM student_expenses
            """
        )
        expenses_row = await exp_cur.fetchone()

    income = dict(income_row) if income_row else {}
    projects = dict(projects_row) if projects_row else {}
    expenses = dict(expenses_row) if expenses_row else {}

    tpm = float(projects.get("total_percent_amount") or 0)
    tpr = float(projects.get("total_percent_received") or 0)

    return {
        "income": {
            "received": income.get("total_received", 0),
            "expected": income.get("total_expected", 0),
            "contracted": income.get("total_contracted", 0),
        },
        "projects": {
            "total_percent": tpm,
            "received_percent": tpr,
            "expected_percent": max(0, tpm - tpr),
        },
        "expenses": {
            "total": expenses.get("total_expenses", 0),
            "paid": expenses.get("paid_expenses", 0),
            "pending": max(
                0,
                float(expenses.get("total_expenses") or 0)
                - float(expenses.get("paid_expenses") or 0),
            ),
        },
    }


@app.get("/api/students")
async def api_list_students(
    status: str | None = Query(None),
    _session=Depends(require_role()),
):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        sql = """
            SELECT s.*,
                   c.name AS client_name,
                   COUNT(DISTINCT sp.id) AS projects_count,
                   COALESCE(SUM(sp.our_amount), 0) AS total_percent_income,
                   COALESCE(SUM(sp.paid_amount), 0) AS paid_percent_income
            FROM students s
            LEFT JOIN clients c ON s.client_id = c.id
            LEFT JOIN student_projects sp ON sp.student_id = s.id
        """
        params: tuple = ()
        if status:
            sql += " WHERE s.status = ?"
            params = (status,)
        sql += """
            GROUP BY s.id
            ORDER BY datetime(s.created_at) DESC
        """
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["balance_expected"] = max(
            0.0,
            float(d.get("student_total") or 0) - float(d.get("student_paid") or 0),
        )
        d["expense_pending"] = max(
            0.0,
            float(d.get("expense_total") or 0) - float(d.get("expense_paid") or 0),
        )
        result.append(d)
    return {"students": result}


@app.post("/api/students")
async def api_create_student(body: StudentCreateBody, _session=Depends(require_role("owner", "pm"))):
    sid = await create_student(body.model_dump(exclude_none=True))
    return {"id": sid}


@app.put("/api/students/{student_id}")
async def api_update_student(
    student_id: int,
    body: StudentUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await update_student(student_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Ученик не найден")
    return {"ok": True}


@app.get("/api/students/{student_id}/tasks")
async def api_list_student_tasks(student_id: int, _auth: bool = Depends(verify_password)):
    if not await get_student(student_id):
        raise HTTPException(status_code=404, detail="Ученик не найден")
    return {"tasks": await get_student_tasks(student_id)}


@app.post("/api/students/{student_id}/tasks")
async def api_add_student_task(
    student_id: int,
    body: StudentTaskBody,
    _session=Depends(require_role("owner", "pm")),
):
    if not await get_student(student_id):
        raise HTTPException(status_code=404, detail="Ученик не найден")
    tid = await create_student_task({
        "student_id": student_id,
        "title": body.title,
        "description": body.description,
        "due_date": body.due_date,
        "status": body.status or "assigned",
    })
    return {"id": tid}


@app.put("/api/student-tasks/{task_id}")
async def api_update_student_task(
    task_id: int,
    body: StudentTaskUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await update_student_task(task_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return {"ok": True}


@app.get("/api/students/{student_id}/progress-logs")
async def api_student_progress_logs(
    student_id: int,
    limit: int = Query(20, ge=1, le=100),
    _auth: bool = Depends(verify_password),
):
    if not await get_student(student_id):
        raise HTTPException(status_code=404, detail="Ученик не найден")
    return {"logs": await list_student_progress_logs(student_id, limit=limit)}


@app.post("/api/students/{student_id}/projects")
async def api_create_student_project(
    student_id: int,
    request: Request,
    _session=Depends(require_role("owner", "pm")),
):
    if not await get_student(student_id):
        raise HTTPException(status_code=404, detail="Ученик не найден")
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название обязательно")

    total = float(data.get("total_amount") or 0)
    percent = float(data.get("our_percent") or 0)
    our_amount = round(total * percent / 100.0, 2)

    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO student_projects
               (student_id, name, description, status,
                total_amount, our_percent, our_amount,
                paid_amount, revenue_type, deadline)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                student_id,
                name,
                data.get("description") or "",
                data.get("status") or "В работе",
                total,
                percent,
                our_amount,
                float(data.get("paid_amount") or 0),
                data.get("revenue_type") or "student",
                data.get("deadline") or "",
            ),
        )
        pid = cur.lastrowid
        await db.commit()
    return {"id": pid, "success": True}


@app.put("/api/students/projects/{pid}")
async def api_update_student_project(
    pid: int,
    request: Request,
    _session=Depends(require_role("owner", "pm")),
):
    try:
        data = await request.json()
    except Exception:
        data = {}
    allowed = {"name", "description", "status", "total_amount", "our_percent", "paid_amount", "revenue_type", "deadline"}
    updates: dict[str, object] = {k: data[k] for k in allowed if k in data}

    db_path = str(DB_PATH)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        if "total_amount" in updates or "our_percent" in updates:
            cur = await db.execute("SELECT * FROM student_projects WHERE id=?", (pid,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Проект не найден")
            rdict = dict(row)
            total = float(updates.get("total_amount", rdict.get("total_amount")) or 0)
            pct = float(updates.get("our_percent", rdict.get("our_percent")) or 0)
            updates["our_amount"] = round(total * pct / 100.0, 2)

        if not updates:
            return {"success": True}

        set_sql = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [pid]
        await db.execute(
            f"UPDATE student_projects SET {set_sql} WHERE id=?",
            vals,
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/students/projects/{pid}")
async def api_delete_student_project(pid: int, _session=Depends(require_role("owner"))):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM student_projects WHERE id=?", (pid,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Проект не найден")
    return {"success": True}


@app.post("/api/students/{student_id}/expenses")
async def api_create_student_expense(
    student_id: int,
    request: Request,
    _session=Depends(require_role("owner")),
):
    if not await get_student(student_id):
        raise HTTPException(status_code=404, detail="Ученик не найден")
    try:
        data = await request.json()
    except Exception:
        data = {}
    desc = (data.get("description") or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Описание обязательно")
    paid_raw = data.get("paid")
    paid = 1 if paid_raw in (1, True, "1", "true") else 0

    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO student_expenses
               (student_id, description, amount, paid, date)
               VALUES (?,?,?,?,?)""",
            (
                student_id,
                desc,
                float(data.get("amount") or 0),
                paid,
                data.get("date") or "",
            ),
        )
        eid = cur.lastrowid
        await db.commit()
    return {"id": eid, "success": True}


@app.put("/api/students/expenses/{eid}")
async def api_update_student_expense(
    eid: int,
    request: Request,
    _session=Depends(require_role("owner")),
):
    try:
        data = await request.json()
    except Exception:
        data = {}
    allowed = {"description", "amount", "paid", "date"}
    updates: dict[str, object] = {}
    for k in allowed:
        if k not in data:
            continue
        v = data[k]
        if k == "paid":
            updates[k] = 1 if v in (1, True, "1", "true") else 0
        else:
            updates[k] = v
    if not updates:
        return {"success": True}
    db_path = str(DB_PATH)
    set_sql = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [eid]
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE student_expenses SET {set_sql} WHERE id=?",
            vals,
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/students/expenses/{eid}")
async def api_delete_student_expense(eid: int, _session=Depends(require_role("owner"))):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM student_expenses WHERE id=?", (eid,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Расход не найден")
    return {"success": True}


@app.post("/api/students/{student_id}/quick-update")
async def api_student_quick_update(
    student_id: int,
    body: StudentQuickUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    student = await get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Ученик не найден")

    action = (body.action or "").strip().lower()
    if action not in {"session_completed", "progress_plus", "stage_update", "activity_log"}:
        raise HTTPException(status_code=400, detail="Некорректное действие")

    if action == "session_completed":
        total_sessions = int(student.get("total_sessions") or 0)
        completed_sessions = int(student.get("completed_sessions") or 0) + 1
        if total_sessions > 0:
            completed_sessions = min(total_sessions, completed_sessions)
        payload = {"completed_sessions": completed_sessions}
        if body.next_session_date:
            payload["next_session_date"] = body.next_session_date
        await update_student(student_id, payload)
        await create_student_progress_log(
            student_id,
            "session_completed",
            note=body.note or "Созвон проведён",
            sessions_delta=1,
            project_id=body.project_id,
        )
    elif action == "progress_plus":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="Нужен project_id")
        project = await get_project(body.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        delta = max(1, min(100, int(body.progress_delta or 10)))
        current_progress = int(project.get("progress") or 0)
        await update_project(body.project_id, {"progress": min(100, current_progress + delta)})
        await create_student_progress_log(
            student_id,
            "progress_plus",
            note=body.note or f"Прогресс проекта +{delta}%",
            progress_delta=delta,
            project_id=body.project_id,
        )
    elif action == "stage_update":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="Нужен project_id")
        project = await get_project(body.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        if not body.stage:
            raise HTTPException(status_code=400, detail="Нужен stage")
        await update_project(body.project_id, {"stage": body.stage})
        await create_student_progress_log(
            student_id,
            "stage_update",
            note=body.note or f"Этап проекта: {body.stage}",
            project_id=body.project_id,
            stage_value=body.stage,
        )
    else:
        await create_student_progress_log(
            student_id,
            "activity_log",
            note=body.note or "Активность зафиксирована",
            project_id=body.project_id,
        )

    return {
        "ok": True,
        "student": await get_student(student_id),
        "logs": await list_student_progress_logs(student_id, limit=8),
    }


@app.post("/api/account-manager/report")
async def api_account_report(
    body: AccountReportBody | None = None,
    _auth: bool = Depends(verify_password),
):
    body = body or AccountReportBody()
    snap = await build_account_snapshot_json()
    extra = (body.prompt_extra or "").strip()
    user_msg = (
        "Сформируй ежедневный отчёт строго по шаблону из твоих инструкций (раздел «ЕЖЕДНЕВНЫЙ ОТЧЁТ»).\n\n"
        f"ДАННЫЕ ИЗ БД (JSON):\n{snap}"
    )
    if extra:
        user_msg += f"\n\nДополнительно от владельца:\n{extra}"
    am = orchestrator.team.account_manager
    resp = await _hq_llm_run(
        am.think(
            user_msg,
            context={"mode": "daily_report"},
            task_id=None,
            max_tokens=8000,
            log_execution=False,
        )
    )
    if not resp.success:
        raise HTTPException(status_code=500, detail=resp.error or "Ошибка LLM")
    out_text = resp.text
    report_id = None
    if body.save:
        payload = json.dumps(
            {"text": out_text, "generated_at": datetime.utcnow().isoformat()},
            ensure_ascii=False,
        )
        report_id = await save_daily_report(date.today().isoformat(), payload)
    return {"text": out_text, "report_id": report_id, "tokens": resp.tokens}


@app.post("/api/account-manager/remind")
async def api_account_remind(
    body: AccountRemindBody | None = None,
    _auth: bool = Depends(verify_password),
):
    body = body or AccountRemindBody()
    items = await _deterministic_today_items()
    result: dict = {"items": items, "ai_summary": None}
    if body.with_ai:
        snap = await build_account_snapshot_json()
        am = orchestrator.team.account_manager
        r = await _hq_llm_run(
            am.think(
                "Кратко (до 1200 символов) перечисли приоритеты на сегодня по данным. Без markdown.\n\n"
                f"ДАННЫЕ:\n{snap}",
                task_id=None,
                max_tokens=1500,
                log_execution=False,
            )
        )
        if r.success:
            result["ai_summary"] = r.text
    return result


@app.get("/api/account-manager/deadlines")
async def api_account_deadlines(_auth: bool = Depends(verify_password)):
    raw = await get_deadlines(14)
    enriched = []
    for row in raw:
        d = dict(row)
        due = d.get("deadline") or d.get("due_date")
        d["urgency"] = _deadline_row_urgency(due)
        enriched.append(d)
    return {"deadlines": enriched}


@app.get("/api/account-manager/today-items")
async def api_today_items(_auth: bool = Depends(verify_password)):
    return {"items": await _deterministic_today_items()}


@app.put("/api/reminders/{reminder_id}")
async def api_update_reminder(
    reminder_id: int,
    body: ReminderUpdateBody,
    _auth: bool = Depends(verify_password),
):
    await update_reminder_sent(reminder_id, body.is_sent)
    return {"ok": True}


@app.get("/api/daily-reports")
async def api_daily_reports_list(
    limit: int = Query(30, ge=1, le=200),
    _auth: bool = Depends(verify_password),
):
    return {"reports": await get_daily_reports(limit)}


@app.get("/api/daily-reports/{report_id}")
async def api_daily_report_one(report_id: int, _auth: bool = Depends(verify_password)):
    row = await get_daily_report_by_id(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    return row


@app.post("/api/agents/{agent_name}/chat")
async def api_agent_chat(
    agent_name: str,
    body: AgentChatBody,
    _session=Depends(require_role("owner", "pm")),
):
    name = agent_name.strip().lower().replace("-", "_")
    agent = orchestrator.team.get(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Агент «{agent_name}» не найден")
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    await add_hq_message(name, "user", msg)
    hist = await get_hq_messages(name, limit=60)
    conv_lines = []
    for m in hist[-40:]:
        role = "Владелец" if m["role"] == "user" else "Агент"
        conv_lines.append(f"{role}: {m['content']}")
    history_block = "\n".join(conv_lines)

    ctx = body.context or {}
    user_full = (
        f"История диалога (последние сообщения):\n{history_block}\n\n"
        f"Новое сообщение владельца:\n{msg}"
    )
    _mt = 8000 if body.max_tokens is None else min(max(int(body.max_tokens), 256), 16000)
    resp = await _hq_llm_run(
        agent.think(
            user_full,
            context={**ctx, "hq_chat": True},
            task_id=None,
            max_tokens=_mt,
            log_execution=False,
        )
    )
    if not resp.success:
        raise HTTPException(status_code=500, detail=resp.error or "Ошибка агента")
    await add_hq_message(name, "assistant", resp.text)
    return {
        "agent": name,
        "text": resp.text,
        "tokens": resp.tokens,
        "model": await get_resolved_hq_model_id(),
    }


@app.get("/api/agents/{agent_name}/chat/history")
async def api_agent_chat_history(
    agent_name: str,
    limit: int = Query(80, ge=1, le=200),
    _auth: bool = Depends(verify_password),
):
    name = agent_name.strip().lower().replace("-", "_")
    if not orchestrator.team.get(name):
        raise HTTPException(status_code=404, detail="Агент не найден")
    return {"messages": await get_hq_messages(name, limit=limit)}


@app.get("/api/metrics/yandex")
async def api_metrics_yandex(_auth: bool = Depends(verify_password)):
    rows = await get_metrics_cache_rows("yandex_")
    parsed = []
    for r in rows:
        item = dict(r)
        try:
            item["value_json"] = json.loads(r["value"]) if r.get("value") else None
        except json.JSONDecodeError:
            item["value_json"] = None
        parsed.append(item)
    return {"cached": parsed, "configured": bool(os.getenv("YANDEX_METRIKA_OAUTH_TOKEN") and os.getenv("YANDEX_METRIKA_COUNTER_ID"))}


@app.get("/api/metrics/business")
async def api_metrics_business(_auth: bool = Depends(verify_password)):
    return await get_business_metrics()


@app.post("/api/metrics/refresh")
async def api_metrics_refresh(_auth: bool = Depends(verify_password)):
    token = (os.getenv("YANDEX_METRIKA_OAUTH_TOKEN") or "").strip()
    counter = (os.getenv("YANDEX_METRIKA_COUNTER_ID") or "").strip()
    today = date.today().isoformat()
    if not token or not counter:
        await upsert_metrics_cache(
            "yandex_status",
            json.dumps({"ok": False, "message": "Задайте YANDEX_METRIKA_OAUTH_TOKEN и YANDEX_METRIKA_COUNTER_ID в .env"}, ensure_ascii=False),
            today,
        )
        return {"ok": False, "message": "Яндекс.Метрика не настроена — сохранена заглушка в кэш"}

    try:
        import aiohttp
        url = (
            "https://api-metrika.yandex.net/stat/v1/data"
            f"?ids={counter}&metrics=ym:s:visits&dimensions=ym:s:date"
            "&date1=30daysAgo&date2=today&accuracy=1&limit=10000"
        )
        headers = {"Authorization": f"OAuth {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                raw_text = await resp.text()
                if resp.status != 200:
                    await upsert_metrics_cache(
                        "yandex_error",
                        json.dumps({"status": resp.status, "body": raw_text[:2000]}, ensure_ascii=False),
                        today,
                    )
                    return {"ok": False, "message": f"API Метрики: HTTP {resp.status}"}
                data = json.loads(raw_text)
        await upsert_metrics_cache("yandex_visits_series", json.dumps(data, ensure_ascii=False), today)
        await upsert_metrics_cache(
            "yandex_status",
            json.dumps({"ok": True, "updated": datetime.utcnow().isoformat()}, ensure_ascii=False),
            today,
        )
        return {"ok": True, "message": "Кэш обновлён"}
    except Exception as e:
        logger.error("Yandex refresh: %s", e, exc_info=True)
        await upsert_metrics_cache(
            "yandex_error",
            json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
            today,
        )
        return {"ok": False, "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# HQ — личные заметки владельца
# ═══════════════════════════════════════════════════════════════════════════

_NOTE_PRIORITIES = frozenset({"low", "normal", "high"})
_NOTE_STATUSES = frozenset({"note", "queued", "done"})


class OwnerNoteCreateBody(BaseModel):
    text: str
    priority: str | None = "normal"


class OwnerNoteUpdateBody(BaseModel):
    text: str | None = None
    status: str | None = None
    priority: str | None = None


@app.get("/api/notes")
async def api_list_owner_notes(_auth: bool = Depends(verify_password)):
    return await list_owner_notes()


@app.post("/api/notes")
async def api_create_owner_note(
    body: OwnerNoteCreateBody,
    _session=Depends(require_role("owner", "pm")),
):
    t = (body.text or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail="Текст заметки не может быть пустым")
    pr = body.priority or "normal"
    if pr not in _NOTE_PRIORITIES:
        raise HTTPException(status_code=400, detail="Некорректный priority")
    return await create_owner_note(t, pr)


@app.put("/api/notes/{note_id}")
async def api_update_owner_note(
    note_id: int,
    body: OwnerNoteUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    if not await get_owner_note(note_id):
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in _NOTE_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный status")
    if "priority" in data and data["priority"] not in _NOTE_PRIORITIES:
        raise HTTPException(status_code=400, detail="Некорректный priority")
    text_val = None
    if "text" in data:
        text_val = (data["text"] or "").strip()
        if not text_val:
            raise HTTPException(status_code=400, detail="Текст не может быть пустым")
    updated = await update_owner_note(
        note_id,
        text=text_val if "text" in data else None,
        status=data.get("status") if "status" in data else None,
        priority=data.get("priority") if "priority" in data else None,
    )
    return updated


@app.delete("/api/notes/{note_id}")
async def api_delete_owner_note(note_id: int, _session=Depends(require_role("owner", "pm"))):
    ok = await delete_owner_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    return {"ok": True}


@app.post("/api/notes/{note_id}/send")
async def api_send_owner_note_to_team(note_id: int, _session=Depends(require_role("owner", "pm"))):
    note = await get_owner_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    if note.get("sent_to_team"):
        raise HTTPException(status_code=400, detail="Заметка уже отправлена команде")
    msg = (note.get("text") or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Пустая заметка")

    task_id = await create_task(msg)
    hq_model = await get_resolved_hq_model_id()
    asyncio.create_task(_run_task_background(msg, task_id, None, hq_model))

    marked = await owner_note_mark_sent_to_team(note_id, task_id)
    if not marked:
        raise HTTPException(status_code=409, detail="Не удалось обновить заметку")

    return {"task_id": task_id, "message": "Задача принята командой"}


# ═══════════════════════════════════════════════════════════════════════════
# HQ — автопостинг в Telegram-канал
# ═══════════════════════════════════════════════════════════════════════════

TELEGRAM_CHANNEL_POST_TARGET = os.getenv("TELEGRAM_CHANNEL_USERNAME", "@AI_Delivery_Agency")
_CHANNEL_POST_STATUSES = frozenset({"draft", "approved", "published", "rejected"})


@app.post("/api/channel/generate")
async def generate_channel_post(
    request: Request,
    _auth: bool = Depends(verify_password),
):
    """
    Принимает JSON: topic, rubric. Цепочка: TelegramWriter → QAEditor.
    Сохраняет в channel_posts со статусом draft.
    """
    data = await request.json()
    topic = (data.get("topic") or "").strip()
    rubric = (data.get("rubric") or "pain").strip() or "pain"
    if not topic:
        raise HTTPException(status_code=400, detail="Укажите тему поста")

    tg_writer = orchestrator.team.get("telegram_writer")
    qa_editor = orchestrator.team.get("qa_editor")
    if not tg_writer or not qa_editor:
        raise HTTPException(status_code=500, detail="Агенты telegram_writer / qa_editor недоступны")

    context = {
        "task": (
            "Напиши пост в Telegram канал агентства по ИИ-автоматизации.\n"
            f"Тема: {topic}\nРубрика: {rubric}"
        ),
        "channel": TELEGRAM_CHANNEL_POST_TARGET,
        "rubric": rubric,
    }
    write_prompt = (
        f"Напиши пост для Telegram канала {TELEGRAM_CHANNEL_POST_TARGET}.\n"
        f"Тема: {topic}\nРубрика: {rubric}\n"
        "Требования: без markdown (#,*,-), только текст и эмодзи, 600–1200 символов, "
        "конкретный CTA в конце."
    )
    write_result = await _hq_llm_run(
        tg_writer.think(
            write_prompt,
            context,
            task_id=None,
            max_tokens=2500,
            log_execution=False,
        )
    )
    if not write_result.success:
        raise HTTPException(
            status_code=500,
            detail=write_result.error or "Ошибка генерации текста",
        )
    post_text = (write_result.text or "").strip()
    if not post_text:
        raise HTTPException(status_code=500, detail="Пустой ответ копирайтера")

    qa_prompt = (
        "Проверь этот пост для Telegram канала агентства по ИИ-автоматизации:\n\n"
        f"{post_text}\n\n"
        "Оцени по шкале 0–100. Ответь строго одним JSON-объектом без markdown:\n"
        '{"score": 85, "notes": "кратко", "approved": true, "improved_text": null}\n'
        "improved_text — строка с исправленным текстом или null, если оставить как есть."
    )
    qa_result = await _hq_llm_run(
        qa_editor.think(
            qa_prompt,
            {"channel": TELEGRAM_CHANNEL_POST_TARGET, "mode": "channel_qa"},
            task_id=None,
            max_tokens=2000,
            log_execution=False,
        )
    )

    qa_score = 75
    qa_notes = ""
    approved = True
    qa_tokens = 0
    if qa_result.success and qa_result.text:
        qa_tokens = qa_result.tokens
        try:
            json_match = re.search(r"\{[\s\S]*\}", qa_result.text)
            if json_match:
                qa_data = json.loads(json_match.group())
                qa_score = int(qa_data.get("score", 75))
                qa_notes = str(qa_data.get("notes") or "")
                approved = bool(qa_data.get("approved", True))
                improved = qa_data.get("improved_text")
                if improved and str(improved).strip():
                    post_text = str(improved).strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    total_tokens = (write_result.tokens or 0) + qa_tokens

    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """INSERT INTO channel_posts
               (topic, rubric, text, status, qa_score, qa_notes, tokens_used)
               VALUES (?, ?, ?, 'draft', ?, ?, ?)""",
            (topic, rubric, post_text, qa_score, qa_notes, total_tokens),
        )
        await db.commit()
        post_id = cursor.lastrowid

    return {
        "post_id": post_id,
        "text": post_text,
        "qa_score": qa_score,
        "qa_notes": qa_notes,
        "approved": approved,
        "tokens_used": total_tokens,
    }


@app.get("/api/channel/posts")
async def get_channel_posts(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _auth: bool = Depends(verify_password),
):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cur = await db.execute(
                "SELECT * FROM channel_posts WHERE status=? ORDER BY datetime(created_at) DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM channel_posts ORDER BY datetime(created_at) DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.put("/api/channel/posts/{post_id}")
async def update_channel_post(
    post_id: int,
    request: Request,
    _auth: bool = Depends(verify_password),
):
    data = await request.json()
    text = data.get("text")
    status = data.get("status")

    updates: list[str] = []
    values: list = []
    if text is not None:
        updates.append("text = ?")
        values.append(text)
    if status is not None:
        if status not in _CHANNEL_POST_STATUSES:
            raise HTTPException(status_code=400, detail="Некорректный status")
        updates.append("status = ?")
        values.append(status)

    if not updates:
        return {"error": "nothing to update"}

    values.append(post_id)
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE channel_posts SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        await db.commit()
    return {"success": True}


@app.post("/api/channel/posts/{post_id}/publish")
async def publish_channel_post(
    post_id: int,
    _auth: bool = Depends(verify_password),
):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM channel_posts WHERE id = ?", (post_id,)
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Post not found")

    post = dict(row)
    body_text = (post.get("text") or "").strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="Текст поста пуст")

    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")

    chat_id = TELEGRAM_CHANNEL_POST_TARGET
    payload = {
        "chat_id": chat_id,
        "text": body_text[:4096],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=30.0,
        )
        try:
            result = resp.json()
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500,
                detail=f"Telegram: неверный ответ HTTP {resp.status_code}",
            ) from None

    if not result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=f"Telegram error: {result.get('description', result)}",
        )

    message_id = result["result"]["message_id"]
    now_iso = datetime.utcnow().isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE channel_posts
               SET status='published', telegram_message_id=?, published_at=?
               WHERE id=?""",
            (message_id, now_iso, post_id),
        )
        await db.commit()

    return {
        "success": True,
        "message_id": message_id,
        "channel": chat_id,
    }


@app.delete("/api/channel/posts/{post_id}")
async def delete_channel_post(
    post_id: int,
    _auth: bool = Depends(verify_password),
):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM channel_posts WHERE id = ?", (post_id,))
        await db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
# HQ — доп. эндпоинты (одна запись CRM)
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/clients/{client_id}")
async def api_get_client_by_id(
    client_id: int,
    _auth: bool = Depends(verify_password),
):
    """Один клиент по id."""
    row = await get_client(client_id)
    if not row:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return row


@app.get("/api/students/{student_id}")
async def api_get_student_by_id(
    student_id: int,
    _session=Depends(require_role()),
):
    """Ученик по id — с проектами ученика и строками расходов."""
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT s.*, c.name AS client_name
               FROM students s
               LEFT JOIN clients c ON s.client_id = c.id
               WHERE s.id=?""",
            (student_id,),
        )
        student = await cur.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Ученик не найден")

        pcur = await db.execute(
            "SELECT * FROM student_projects WHERE student_id=? ORDER BY datetime(created_at) DESC",
            (student_id,),
        )
        projects = await pcur.fetchall()

        ecur = await db.execute(
            "SELECT * FROM student_expenses WHERE student_id=? ORDER BY datetime(created_at) DESC",
            (student_id,),
        )
        expenses = await ecur.fetchall()

    result = dict(student)
    result["projects"] = [dict(r) for r in projects]
    result["expenses"] = [dict(r) for r in expenses]
    return result


# ═══════════════════════════════════════════════════════════════════════════
# CRUD-алиасы (доп. пути из контракта API)
# ═══════════════════════════════════════════════════════════════════════════


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: int, _=Depends(require_role("owner", "pm"))):
    """Удаление CRM-проекта — owner или pm (P2-5)."""
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM project_tasks WHERE project_id = ?", (project_id,))
        await db.execute("UPDATE tasks_v2 SET project_id = NULL WHERE project_id = ?", (project_id,))
        await db.execute("UPDATE kanban_notes SET linked_task_id = NULL WHERE linked_task_id IN (SELECT id FROM project_tasks WHERE project_id = ?)", (project_id,))
        cur = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Проект не найден")
    return {"ok": True}


@app.put("/api/project-tasks/{task_id}")
async def api_update_project_task_rest(
    task_id: int,
    body: ProjectTaskUpdateBody,
    _session=Depends(require_role("owner", "pm")),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = await update_project_task(task_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"ok": True}


@app.delete("/api/project-tasks/{task_id}")
async def api_delete_project_task(task_id: int, _session=Depends(require_role("owner", "pm"))):
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM project_tasks WHERE id = ?", (task_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"ok": True}


@app.delete("/api/students/{student_id}")
async def api_delete_student(student_id: int, _=Depends(require_role("owner"))):
    """Удаление ученика — только owner (P2-5)."""
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM students WHERE id = ?", (student_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ученик не найден")
    return {"ok": True}


# ── HQ v3.0 API (регистрация в конце файла) ──
from hq_v3_api import mount_hq_v3_routes

mount_hq_v3_routes(app, orchestrator, verify_password, _hq_llm_run, require_role, get_optional_hq_session)


# ═══════════════════════════════════════════════════════════════════════════
#  ПРОИЗВОДСТВО (Delivery): отдельный bounded context от CRM projects
# ═══════════════════════════════════════════════════════════════════════════

DELIVERY_BASE_CHECKLIST = [
    "PR прикреплён",
    "Vercel Preview прикреплён",
    "Задача соответствует ТЗ",
    "Desktop проверен",
    "Mobile проверен",
    "Нет ошибок в консоли",
]

# Чеклист по умолчанию при развёртывании шаблона (PRD промпт 6)
DELIVERY_TEMPLATE_TASK_CHECKLIST = [
    "Задача соответствует ТЗ",
    "Результат задокументирован",
    "Проверено на мобиле (если frontend)",
]

ALLOWED_PROJECT_STATUS = {
    "Подготовка", "В работе", "На проверке", "Завершён", "Заморожен", "Черновик",
    "Ожидает клиента",
    "Запущен",
}
ALLOWED_TASK_STATUS = {
    "Backlog", "Ready", "In Progress", "Review", "Approved", "Done", "Blocked",
    "Changes Requested", "Cancelled",
}
ALLOWED_PRIORITY = {"Critical", "High", "Medium", "Low"}


async def _executor_id_for_user(db: aiosqlite.Connection, user_id: int | None) -> int | None:
    """Найти executor.id привязанный к hq_users.id (или None)."""
    if not user_id:
        return None
    cur = await db.execute("SELECT id FROM executors WHERE user_id=? LIMIT 1", (user_id,))
    row = await cur.fetchone()
    return row[0] if row else None


def _delivery_recalc_our_amount(merged: dict) -> float:
    """Наша сумма от student-проекта: budget * our_percent / 100."""
    budget = float(merged.get("budget") or 0)
    owner_type = (merged.get("owner_type") or "agency").strip()
    pct = float(merged.get("our_percent") or 0)
    if owner_type == "student" and budget > 0:
        return round(budget * pct / 100, 2)
    return 0.0


def _delivery_norm_owner_type(v: str | None) -> str:
    s = (v or "agency").strip()
    return s if s in ("agency", "student") else "agency"


def _delivery_norm_student_id(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ─── DELIVERY PROJECTS ────────────────────────────────────────────────────

@app.get("/api/delivery/projects")
async def api_delivery_projects_list(session=Depends(require_role())):
    """Список проектов производства с агрегатами по задачам."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT dp.*,
               c.name AS client_name,
               s.name AS student_name,
               s.status AS student_status,
               (SELECT COUNT(*) FROM delivery_tasks dt WHERE dt.project_id=dp.id) AS task_count,
               (SELECT COUNT(*) FROM delivery_tasks dt WHERE dt.project_id=dp.id AND dt.status='Review') AS review_count,
               (SELECT COUNT(*) FROM delivery_tasks dt WHERE dt.project_id=dp.id AND dt.status='Done') AS done_count,
               (SELECT COUNT(*) FROM delivery_tasks dt WHERE dt.project_id=dp.id
                 AND dt.deadline != '' AND dt.deadline < date('now')
                 AND dt.status NOT IN ('Done','Cancelled')) AS overdue_count
               FROM delivery_projects dp
               LEFT JOIN clients c ON dp.client_id = c.id
               LEFT JOIN students s ON dp.student_id = s.id
               ORDER BY dp.created_at DESC"""
        )
        rows = await cur.fetchall()
    return {"projects": [dict(r) for r in rows]}


@app.post("/api/delivery/projects")
async def api_delivery_project_create(request: Request, session=Depends(require_role("owner", "pm"))):
    """Создать проект. Если template_id задан — автогенерация этапов и задач."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Название обязательно")
    status = (data.get("status") or "Подготовка").strip()
    if status not in ALLOWED_PROJECT_STATUS:
        status = "Подготовка"
    priority = (data.get("priority") or "Medium").strip()
    if priority not in ALLOWED_PRIORITY:
        priority = "Medium"

    owner_type = _delivery_norm_owner_type(data.get("owner_type"))
    student_id = _delivery_norm_student_id(data.get("student_id"))
    our_percent = float(data.get("our_percent") or 0)
    notes = (data.get("notes") or "").strip()
    budget_val = float(data.get("budget") or 0)
    merged_for_amt = {
        "budget": budget_val,
        "owner_type": owner_type,
        "our_percent": our_percent,
    }
    our_amount = _delivery_recalc_our_amount(merged_for_amt)

    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            """INSERT INTO delivery_projects
               (name, client_id, crm_project_id, description, type, status, owner_id,
                github_repo_url, vercel_project_url, production_url,
                start_date, deadline, budget, priority,
                student_id, owner_type, our_percent, our_amount, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,
                data.get("client_id") or None,
                data.get("crm_project_id") or None,
                data.get("description") or "",
                data.get("type") or "Другое",
                status,
                session.get("user_id") or 1,
                data.get("github_repo_url") or "",
                data.get("vercel_project_url") or "",
                data.get("production_url") or "",
                data.get("start_date") or "",
                data.get("deadline") or "",
                budget_val,
                priority,
                student_id,
                owner_type,
                our_percent,
                our_amount,
                notes,
            ),
        )
        project_id = cur.lastrowid
        await db.commit()

    # Применить шаблон (если выбран)
    template_id = data.get("template_id")
    if template_id:
        await _apply_delivery_template(int(template_id), int(project_id))

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM delivery_projects WHERE id=?", (project_id,))
        row = await cur.fetchone()
    return dict(row) if row else {"id": project_id}


async def _apply_delivery_template(template_id: int, project_id: int) -> None:
    """Развернуть шаблон в этапы + задачи проекта."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT stages_json FROM delivery_templates WHERE id=?", (template_id,))
        row = await cur.fetchone()
        if not row:
            return
        try:
            stages = json.loads(row["stages_json"] or "[]")
        except Exception:
            return
        for i, stage_data in enumerate(stages):
            cur = await db.execute(
                "INSERT INTO delivery_stages (project_id, name, stage_order) VALUES (?,?,?)",
                (project_id, stage_data.get("name", f"Этап {i+1}"), i),
            )
            stage_id = cur.lastrowid
            for task_title in stage_data.get("tasks", []):
                tcur = await db.execute(
                    """INSERT INTO delivery_tasks (project_id, stage_id, title, status, priority)
                       VALUES (?,?,?,'Backlog','Medium')""",
                    (project_id, stage_id, task_title),
                )
                tid = tcur.lastrowid
                for item in DELIVERY_TEMPLATE_TASK_CHECKLIST:
                    await db.execute(
                        "INSERT INTO delivery_checklist (task_id, title) VALUES (?,?)",
                        (tid, item),
                    )
        await db.commit()


@app.get("/api/delivery/projects/{pid}")
async def api_delivery_project_get(pid: int, session=Depends(require_role())):
    """Получить проект с информацией о клиенте."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT dp.*, c.name AS client_name, c.contact AS client_contact,
               s.name AS student_name,
               s.student_paid AS student_paid,
               s.student_total AS student_total
               FROM delivery_projects dp
               LEFT JOIN clients c ON dp.client_id = c.id
               LEFT JOIN students s ON dp.student_id = s.id
               WHERE dp.id=?""",
            (pid,),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Проект не найден")
    return dict(row)


@app.put("/api/delivery/projects/{pid}")
async def api_delivery_project_update(pid: int, request: Request, session=Depends(require_role("owner", "pm"))):
    """Обновить проект."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    allowed = [
        "name", "client_id", "crm_project_id", "description", "type", "status",
        "github_repo_url", "vercel_project_url", "production_url",
        "start_date", "deadline", "budget", "priority",
        "student_id", "owner_type", "our_percent", "notes",
    ]
    updates = {k: data[k] for k in allowed if k in data}
    if "status" in updates and updates["status"] not in ALLOWED_PROJECT_STATUS:
        raise HTTPException(400, "Недопустимый статус")
    if "priority" in updates and updates["priority"] not in ALLOWED_PRIORITY:
        raise HTTPException(400, "Недопустимый приоритет")
    if "budget" in updates:
        updates["budget"] = float(updates["budget"] or 0)
    if "our_percent" in updates:
        updates["our_percent"] = float(updates["our_percent"] or 0)
    if "owner_type" in updates:
        updates["owner_type"] = _delivery_norm_owner_type(updates["owner_type"])
    if "student_id" in updates:
        updates["student_id"] = _delivery_norm_student_id(updates["student_id"])
    if "notes" in updates and isinstance(updates["notes"], str):
        updates["notes"] = updates["notes"].strip()
    if not updates:
        return {"success": True}

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM delivery_projects WHERE id=?", (pid,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Проект не найден")
        merged = dict(row)
        merged.update(updates)
        merged["owner_type"] = _delivery_norm_owner_type(merged.get("owner_type"))
        merged["budget"] = float(merged.get("budget") or 0)
        merged["our_percent"] = float(merged.get("our_percent") or 0)
        updates["our_amount"] = _delivery_recalc_our_amount(merged)

        set_sql = ", ".join(f"{k}=?" for k in updates.keys()) + ", updated_at=CURRENT_TIMESTAMP"
        await db.execute(
            f"UPDATE delivery_projects SET {set_sql} WHERE id=?",
            list(updates.values()) + [pid],
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/delivery/projects/{pid}")
async def api_delivery_project_delete(pid: int, session=Depends(require_role("owner"))):
    """Удалить проект и всё связанное (каскад через FK)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute("DELETE FROM delivery_projects WHERE id=?", (pid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Проект не найден")
        await db.commit()
    return {"success": True}


@app.post("/api/delivery/projects/{pid}/apply_template")
async def api_delivery_project_apply_template(
    pid: int, request: Request, session=Depends(require_role("owner", "pm"))
):
    """Применить шаблон к существующему проекту (этапы и задачи добавляются к проекту)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    tid = data.get("template_id")
    if tid is None:
        raise HTTPException(400, "template_id обязателен")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute("SELECT id FROM delivery_projects WHERE id=?", (pid,))
        if not await cur.fetchone():
            raise HTTPException(404, "Проект не найден")
    await _apply_delivery_template(int(tid), pid)
    return {"success": True}


# ─── STAGES ───────────────────────────────────────────────────────────────

@app.get("/api/delivery/projects/{pid}/stages")
async def api_delivery_stages_list(pid: int, session=Depends(require_role())):
    """Список этапов проекта с агрегатами по задачам."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT s.*,
               COUNT(t.id) AS task_count,
               SUM(CASE WHEN t.status='Done' THEN 1 ELSE 0 END) AS done_count
               FROM delivery_stages s
               LEFT JOIN delivery_tasks t ON t.stage_id = s.id
               WHERE s.project_id=?
               GROUP BY s.id
               ORDER BY s.stage_order, s.id""",
            (pid,),
        )
        rows = await cur.fetchall()
    return {"stages": [dict(r) for r in rows]}


@app.post("/api/delivery/projects/{pid}/stages")
async def api_delivery_stage_create(pid: int, request: Request, session=Depends(require_role("owner", "pm"))):
    """Создать этап в проекте."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT MAX(stage_order) FROM delivery_stages WHERE project_id=?", (pid,)
        )
        row = await cur.fetchone()
        max_order = (row[0] or -1) + 1
        cur = await db.execute(
            "INSERT INTO delivery_stages "
            "(project_id, name, description, deadline, stage_order) VALUES (?,?,?,?,?)",
            (
                pid,
                (data.get("name") or "Новый этап").strip(),
                data.get("description") or "",
                data.get("deadline") or "",
                max_order,
            ),
        )
        sid = cur.lastrowid
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM delivery_stages WHERE id=?", (sid,))
        row = await cur.fetchone()
    return dict(row) if row else {"id": sid}


@app.put("/api/delivery/stages/{sid}")
async def api_delivery_stage_update(sid: int, request: Request, session=Depends(require_role("owner", "pm"))):
    """Обновить этап."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    allowed = ["name", "description", "status", "deadline", "stage_order", "start_date"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return {"success": True}
    set_sql = ", ".join(f"{k}=?" for k in updates.keys()) + ", updated_at=CURRENT_TIMESTAMP"
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE delivery_stages SET {set_sql} WHERE id=?",
            list(updates.values()) + [sid],
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/delivery/stages/{sid}")
async def api_delivery_stage_delete(sid: int, session=Depends(require_role("owner", "pm"))):
    """Удалить этап. Задачи остаются с stage_id=NULL."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("UPDATE delivery_tasks SET stage_id=NULL WHERE stage_id=?", (sid,))
        await db.execute("DELETE FROM delivery_stages WHERE id=?", (sid,))
        await db.commit()
    return {"success": True}


# ─── DELIVERY TASKS ────────────────────────────────────────────────────────

@app.get("/api/delivery/tasks")
async def api_delivery_tasks_list(
    request: Request,
    project_id: int | None = None,
    stage_id: int | None = None,
    assignee_id: int | None = None,
    status: str | None = None,
    my_tasks: bool = False,
    session=Depends(require_role()),
):
    """Список задач с фильтрами. executor видит только свои; my_tasks=true тоже."""
    conds: list[str] = []
    params: list = []
    if project_id is not None:
        conds.append("t.project_id=?")
        params.append(project_id)
    if stage_id is not None:
        conds.append("t.stage_id=?")
        params.append(stage_id)
    if assignee_id is not None:
        conds.append("t.assignee_id=?")
        params.append(assignee_id)
    if status:
        conds.append("t.status=?")
        params.append(status)

    # Executor / my_tasks → фильтр по своему executor_id
    if session["role"] == "executor" or my_tasks:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            ex_id = await _executor_id_for_user(db, session.get("user_id"))
        if ex_id is None:
            # Нет привязки → пустой список (защита от утечки чужих задач)
            return {"tasks": []}
        conds.append("t.assignee_id=?")
        params.append(ex_id)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        sql = f"""
            SELECT t.*,
                   dp.name AS project_name,
                   ds.name AS stage_name,
                   e1.name AS assignee_name,
                   e2.name AS reviewer_name
            FROM delivery_tasks t
            LEFT JOIN delivery_projects dp ON t.project_id = dp.id
            LEFT JOIN delivery_stages ds ON t.stage_id = ds.id
            LEFT JOIN executors e1 ON t.assignee_id = e1.id
            LEFT JOIN executors e2 ON t.reviewer_id = e2.id
            {where}
            ORDER BY
              CASE t.priority
                WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                WHEN 'Medium' THEN 3 ELSE 4 END,
              CASE WHEN t.deadline = '' THEN 1 ELSE 0 END,
              t.deadline ASC
        """
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return {"tasks": [dict(r) for r in rows]}


@app.post("/api/delivery/tasks")
async def api_delivery_task_create(request: Request, session=Depends(require_role("owner", "pm"))):
    """Создать задачу. Базовый чеклист добавляется автоматически."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Название обязательно")
    pid = data.get("project_id")
    if not pid:
        raise HTTPException(400, "project_id обязателен")
    status = (data.get("status") or "Backlog").strip()
    if status not in ALLOWED_TASK_STATUS:
        status = "Backlog"
    priority = (data.get("priority") or "Medium").strip()
    if priority not in ALLOWED_PRIORITY:
        priority = "Medium"
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            """INSERT INTO delivery_tasks
               (project_id, stage_id, title, description, goal,
                assignee_id, reviewer_id, status, priority, deadline, branch_name)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pid,
                data.get("stage_id"),
                title,
                data.get("description") or "",
                data.get("goal") or "",
                data.get("assignee_id"),
                data.get("reviewer_id"),
                status,
                priority,
                data.get("deadline") or "",
                data.get("branch_name") or "",
            ),
        )
        task_id = cur.lastrowid
        for item in DELIVERY_BASE_CHECKLIST:
            await db.execute(
                "INSERT INTO delivery_checklist (task_id, title) VALUES (?,?)",
                (task_id, item),
            )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM delivery_tasks WHERE id=?", (task_id,))
        row = await cur.fetchone()
    return dict(row) if row else {"id": task_id}


@app.get("/api/delivery/tasks/{tid}")
async def api_delivery_task_get(tid: int, session=Depends(require_role())):
    """Полная карточка задачи: с чеклистом, комментариями, joins."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*,
                   dp.name AS project_name,
                   ds.name AS stage_name,
                   e1.name AS assignee_name,
                   e1.user_id AS assignee_user_id,
                   e2.name AS reviewer_name,
                   e2.user_id AS reviewer_user_id
            FROM delivery_tasks t
            LEFT JOIN delivery_projects dp ON t.project_id = dp.id
            LEFT JOIN delivery_stages ds ON t.stage_id = ds.id
            LEFT JOIN executors e1 ON t.assignee_id = e1.id
            LEFT JOIN executors e2 ON t.reviewer_id = e2.id
            WHERE t.id=?""",
            (tid,),
        )
        task = await cur.fetchone()
        if not task:
            raise HTTPException(404, "Задача не найдена")
        cur = await db.execute(
            "SELECT * FROM delivery_checklist WHERE task_id=? ORDER BY id", (tid,)
        )
        checklist = await cur.fetchall()
        cur = await db.execute(
            "SELECT * FROM delivery_comments WHERE task_id=? ORDER BY created_at, id", (tid,)
        )
        comments = await cur.fetchall()

    # Executor видит только свои задачи (защита от прямого URL)
    if session["role"] == "executor":
        user_id = session.get("user_id")
        if task["assignee_user_id"] != user_id:
            raise HTTPException(403, "Это не ваша задача")

    result = dict(task)
    result["checklist"] = [dict(r) for r in checklist]
    result["comments"] = [dict(r) for r in comments]
    return result


@app.put("/api/delivery/tasks/{tid}")
async def api_delivery_task_update(tid: int, request: Request, session=Depends(require_role())):
    """Обновить задачу. Поля доступные для редактирования зависят от роли."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    role = session["role"]
    if role == "executor":
        # Защита: executor может менять только СВОЮ задачу
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT t.assignee_id, e.user_id FROM delivery_tasks t "
                "LEFT JOIN executors e ON t.assignee_id = e.id WHERE t.id=?",
                (tid,),
            )
            row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")
        if row["user_id"] != session.get("user_id"):
            raise HTTPException(403, "Это не ваша задача")
        allowed = ["status", "pull_request_url", "preview_url", "result_comment", "branch_name"]
    elif role == "reviewer":
        allowed = ["status", "review_comment"]
    elif role in {"owner", "pm"}:
        allowed = [
            "title", "description", "goal", "stage_id", "assignee_id", "reviewer_id",
            "status", "priority", "deadline", "branch_name", "pull_request_url",
            "preview_url", "production_url", "result_comment", "review_comment",
        ]
    else:
        raise HTTPException(403, "Нет прав")

    updates = {k: data[k] for k in allowed if k in data}
    if "status" in updates and updates["status"] not in ALLOWED_TASK_STATUS:
        raise HTTPException(400, "Недопустимый статус")
    if "priority" in updates and updates["priority"] not in ALLOWED_PRIORITY:
        raise HTTPException(400, "Недопустимый приоритет")
    if not updates:
        return {"success": True}
    set_sql = ", ".join(f"{k}=?" for k in updates.keys()) + ", updated_at=CURRENT_TIMESTAMP"
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE delivery_tasks SET {set_sql} WHERE id=?",
            list(updates.values()) + [tid],
        )
        await db.commit()
    return {"success": True}


@app.delete("/api/delivery/tasks/{tid}")
async def api_delivery_task_delete(tid: int, session=Depends(require_role("owner", "pm"))):
    """Удалить задачу. Чеклист и комментарии удалятся каскадом."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute("DELETE FROM delivery_tasks WHERE id=?", (tid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Задача не найдена")
        await db.commit()
    return {"success": True}


# ─── CHECKLIST ─────────────────────────────────────────────────────────────

@app.put("/api/delivery/checklist/{item_id}")
async def api_delivery_checklist_toggle(item_id: int, request: Request, session=Depends(require_role())):
    """Переключить чеклист-пункт. Доступно всем ролям с авторизацией."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    is_done = 1 if data.get("is_completed") else 0
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "UPDATE delivery_checklist SET is_completed=? WHERE id=?",
            (is_done, item_id),
        )
        await db.commit()
    return {"success": True}


@app.post("/api/delivery/tasks/{tid}/checklist")
async def api_delivery_checklist_add(tid: int, request: Request, session=Depends(require_role("owner", "pm"))):
    """Добавить пункт в чеклист задачи."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Название пункта обязательно")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "INSERT INTO delivery_checklist (task_id, title) VALUES (?,?)",
            (tid, title),
        )
        await db.commit()
        item_id = cur.lastrowid
    return {"success": True, "id": item_id}


# ─── COMMENTS ──────────────────────────────────────────────────────────────

@app.post("/api/delivery/tasks/{tid}/comments")
async def api_delivery_comment_add(tid: int, request: Request, session=Depends(require_role())):
    """Добавить комментарий к задаче."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    body = (data.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Комментарий пустой")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "INSERT INTO delivery_comments (task_id, user_id, author_name, body) VALUES (?,?,?,?)",
            (tid, session.get("user_id"), session.get("name", ""), body),
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM delivery_comments WHERE id=?", (cur.lastrowid,))
        row = await cur.fetchone()
    return dict(row) if row else {"success": True}


# ─── EXECUTORS ─────────────────────────────────────────────────────────────

@app.get("/api/delivery/executors")
async def api_delivery_executors_list(session=Depends(require_role())):
    """Список исполнителей: delivery + tasks_v2, уровень, загрузка (без смешения join-строк).

    Совместимость team-settings.html: поля active_tasks / review_tasks / overdue_tasks считаются
    только по delivery_tasks (как раньше). Дополнительно: tasks_active, delivery_*, total_active.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT e.*,
                   u.login AS user_login,
                   u.role AS user_role,
                   (SELECT COUNT(*)
                      FROM delivery_tasks dt
                     WHERE dt.assignee_id = e.id
                       AND dt.status NOT IN ('Done','Cancelled','Approved')) AS delivery_active,
                   (SELECT COUNT(*)
                      FROM delivery_tasks dt
                     WHERE dt.assignee_id = e.id
                       AND dt.status = 'Review') AS delivery_review,
                   (SELECT COUNT(*)
                      FROM delivery_tasks dt
                     WHERE dt.assignee_id = e.id
                       AND COALESCE(TRIM(dt.deadline), '') != ''
                       AND date(dt.deadline) < date('now')
                       AND dt.status NOT IN ('Done','Cancelled')) AS delivery_overdue,
                   (SELECT COUNT(*)
                      FROM tasks_v2 tv
                     WHERE e.user_id IS NOT NULL
                       AND tv.assignee_id = e.user_id
                       AND tv.status NOT IN ('готово','отменена')) AS tasks_active
              FROM executors e
              LEFT JOIN hq_users u ON e.user_id = u.id
          ORDER BY e.name
            """
        )
        rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        da = int(d.get("delivery_active") or 0)
        dr = int(d.get("delivery_review") or 0)
        do = int(d.get("delivery_overdue") or 0)
        tv_n = int(d.get("tasks_active") or 0)
        d["active_tasks"] = da
        d["review_tasks"] = dr
        d["overdue_tasks"] = do

        active = da + tv_n
        d["total_active"] = active
        d["load_status"] = (
            "Перегружен"
            if active >= 5
            else ("Высокая загрузка" if active >= 3 else ("Загружен" if active >= 1 else "Доступен"))
        )
        d["load_color"] = (
            "#ef4444" if active >= 5 else ("#f59e0b" if active >= 3 else ("#22c55e" if active >= 1 else "#606060"))
        )
        executor_status = (d.get("status") or "").strip()
        if executor_status in ("На паузе", "Неактивен"):
            if executor_status == "На паузе":
                d["load_status"] = "На паузе"
                d["load_color"] = "#94a3b8"
            else:
                d["load_status"] = "Неактивен"
                d["load_color"] = "#475569"

        level = (d.get("level") or "middle").strip().lower()
        if level not in ("junior", "middle", "senior"):
            level = "middle"
        d["level"] = level

        out.append(d)
    return {"executors": out}


@app.post("/api/delivery/executors")
async def api_delivery_executor_create(request: Request, session=Depends(require_role("owner", "pm"))):
    """Создать исполнителя. user_id опциональный (привязка к hq_users)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Имя обязательно")
    lvl = (data.get("level") or "middle").strip().lower()
    if lvl not in ("junior", "middle", "senior"):
        lvl = "middle"
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "INSERT INTO executors "
            "(user_id, name, role, telegram, email, github_username, specialization, status, level) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                data.get("user_id") or None,
                name,
                (data.get("role") or "executor").strip(),
                data.get("telegram") or "",
                data.get("email") or "",
                data.get("github_username") or "",
                data.get("specialization") or "",
                data.get("status") or "Доступен",
                lvl,
            ),
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM executors WHERE id=?", (cur.lastrowid,))
        row = await cur.fetchone()
    return dict(row) if row else {"success": True}


@app.put("/api/delivery/executors/{eid}")
async def api_delivery_executor_update(eid: int, request: Request, session=Depends(require_role("owner", "pm"))):
    """Обновить исполнителя."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Неверный JSON")
    allowed = [
        "user_id",
        "name",
        "role",
        "telegram",
        "email",
        "github_username",
        "specialization",
        "status",
        "level",
    ]
    updates = {k: data[k] for k in allowed if k in data}
    if "level" in updates:
        lev = str(updates["level"]).strip().lower()
        updates["level"] = lev if lev in ("junior", "middle", "senior") else "middle"
    if not updates:
        return {"success": True}
    set_sql = ", ".join(f"{k}=?" for k in updates.keys())
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE executors SET {set_sql} WHERE id=?",
            list(updates.values()) + [eid],
        )
        await db.commit()
    return {"success": True}


@app.get("/api/delivery/executors/{eid}/tasks")
async def api_delivery_executor_tasks(
    eid: int, session=Depends(require_role("owner", "pm"))
):
    """Активные delivery_tasks и tasks_v2 (по hq_users), назначенные этому исполнителю."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, user_id FROM executors WHERE id=?", (eid,))
        ex = await cur.fetchone()
        if not ex:
            raise HTTPException(status_code=404, detail="Исполнитель не найден")
        user_uid = dict(ex).get("user_id")

        cur = await db.execute(
            """SELECT dt.*,
               dp.name AS project_name,
               ds.name AS stage_name
               FROM delivery_tasks dt
               LEFT JOIN delivery_projects dp ON dt.project_id = dp.id
               LEFT JOIN delivery_stages ds ON dt.stage_id = ds.id
               WHERE dt.assignee_id = ?
               AND dt.status NOT IN ('Done','Cancelled')
               ORDER BY
                 CASE WHEN COALESCE(TRIM(dt.deadline), '') = '' THEN 1 ELSE 0 END,
                 dt.deadline ASC""",
            (eid,),
        )
        delivery_tasks = [dict(r) for r in await cur.fetchall()]

        tasks_v2: list = []
        if user_uid:
            cur = await db.execute(
                """SELECT tv.*, c.name AS client_name, p.name AS project_name
                   FROM tasks_v2 tv
                   LEFT JOIN clients c ON tv.client_id = c.id
                   LEFT JOIN projects p ON tv.project_id = p.id
                   WHERE tv.assignee_id = ?
                   AND tv.status NOT IN ('готово','отменена')
                   ORDER BY CASE WHEN COALESCE(TRIM(tv.due_date), TRIM(tv.deadline), '') = ''
                                 THEN 1 ELSE 0 END,
                            tv.due_date ASC""",
                (user_uid,),
            )
            tasks_v2 = [dict(r) for r in await cur.fetchall()]

    return {"delivery_tasks": delivery_tasks, "tasks_v2": tasks_v2}


@app.delete("/api/delivery/executors/{eid}")
async def api_delivery_executor_delete(eid: int, session=Depends(require_role("owner"))):
    """Удалить исполнителя. Назначения на задачах обнулятся (FK SET NULL)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("DELETE FROM executors WHERE id=?", (eid,))
        await db.commit()
    return {"success": True}


# ─── TEMPLATES ─────────────────────────────────────────────────────────────

@app.get("/api/delivery/templates")
async def api_delivery_templates_list(session=Depends(require_role())):
    """Список шаблонов проектов (метаданные + этапы для UI)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, type, icon, estimated_days, description, stages_json FROM delivery_templates ORDER BY id"
        )
        rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["stages"] = json.loads(d.get("stages_json") or "[]")
        except Exception:
            d["stages"] = []
        d.pop("stages_json", None)
        out.append(d)
    return {"templates": out}


# ─── OVERVIEW ──────────────────────────────────────────────────────────────

@app.get("/api/delivery/overview")
async def api_delivery_overview(session=Depends(require_role())):
    """Сводные метрики производства для дашборда."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        async def _c(sql: str, params: tuple = ()) -> int:
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            return int(row[0] or 0) if row else 0

        active_projects = await _c(
            "SELECT COUNT(*) FROM delivery_projects "
            "WHERE status NOT IN ('Завершён','Заморожен','Черновик')"
        )
        in_progress = await _c("SELECT COUNT(*) FROM delivery_tasks WHERE status='In Progress'")
        in_review = await _c("SELECT COUNT(*) FROM delivery_tasks WHERE status='Review'")
        overdue = await _c(
            "SELECT COUNT(*) FROM delivery_tasks "
            "WHERE deadline != '' AND deadline < date('now') "
            "AND status NOT IN ('Done','Cancelled')"
        )
        blocked = await _c("SELECT COUNT(*) FROM delivery_tasks WHERE status='Blocked'")
        student_projects_count = await _c(
            "SELECT COUNT(*) FROM delivery_projects WHERE owner_type='student'"
        )
        agency_projects = await _c(
            "SELECT COUNT(*) FROM delivery_projects "
            "WHERE COALESCE(owner_type,'agency') != 'student'"
        )
    return {
        "active_projects": active_projects,
        "in_progress": in_progress,
        "in_review": in_review,
        "overdue": overdue,
        "blocked": blocked,
        "agency_projects": agency_projects,
        "student_projects_count": student_projects_count,
    }
