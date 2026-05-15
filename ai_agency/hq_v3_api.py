"""
HQ v3.0 — дополнительные эндпоинты. Подключается из api.py в конце инициализации приложения.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Awaitable

import aiosqlite
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from agency_context_loader import invalidate_cache
from database import (
    DB_PATH,
    add_hq_message,
    create_task as db_create_owner_task,
    count_unread_notifications,
    delete_idea_row,
    delete_kanban_note_row,
    delete_knowledge_row,
    delete_payment_row,
    delete_task_v2,
    delete_tasks_v2_checklist_item,
    delete_tasks_v2_comment,
    get_business_metrics,
    get_clients,
    get_client,
    get_app_setting,
    get_task,
    get_idea,
    get_kanban_note,
    get_knowledge_row,
    get_economics_month,
    get_payment,
    get_project,
    get_projects,
    get_student,
    get_students,
    get_task_v2,
    get_task_v2_detail,
    get_tasks_v2_comment,
    insert_idea,
    insert_kanban_note,
    insert_knowledge_row,
    insert_notification,
    insert_payment,
    insert_tasks_v2_checklist_item,
    insert_tasks_v2_comment,
    insert_task_v2,
    insert_timeline_event,
    list_economics_months,
    list_ideas,
    list_kanban_notes,
    list_knowledge_rows,
    list_notifications,
    list_payments_for_client,
    get_team_tasks_history,
    list_tasks_v2,
    list_timeline_events,
    mark_all_notifications_read,
    mark_notification_read,
    recalc_client_paid_from_payments,
    search_knowledge_simple,
    sync_task_v2_ai_link,
    tasks_v2_checklist_task_id_for_item,
    update_tasks_v2_checklist_completed,
    upsert_economics_month,
    update_idea_row,
    update_kanban_note_row,
    update_knowledge_row,
    update_payment_row,
    update_task_v2,
)

logger = logging.getLogger("hq_v3_api")

# T-1-012 (Sprint 1): in-memory _sessions dict removed. Sessions now live in
# the `hq_sessions` table; api.py imports session_store directly.

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "data" / "knowledge"


class PaymentCreateBody(BaseModel):
    amount: float
    status: str | None = "ожидается"
    description: str | None = ""
    due_date: str | None = ""
    paid_date: str | None = ""
    invoice_number: str | None = ""


class PaymentUpdateBody(BaseModel):
    amount: float | None = None
    status: str | None = None
    description: str | None = None
    due_date: str | None = None
    paid_date: str | None = None
    invoice_number: str | None = None


class TimelinePostBody(BaseModel):
    entity_type: str
    entity_id: int
    event_type: str
    title: str
    description: str | None = ""
    meta: dict | None = None
    created_by: str | None = "owner"


class TaskV2CreateBody(BaseModel):
    title: str
    description: str | None = ""
    type: str | None = "задача"
    status: str | None = "новая"
    priority: str | None = "средний"
    client_id: int | None = None
    project_id: int | None = None
    student_id: int | None = None
    assignee: str | None = ""
    assignee_id: int | None = None
    goal: str | None = ""
    result: str | None = ""
    agent_initiator: str | None = ""
    idea_id: int | None = None
    due_date: str | None = ""
    execution_date: str | None = ""
    deadline: str | None = ""
    checklist: str | None = "[]"
    tags: str | None = "[]"
    source: str | None = ""
    source_id: int | None = None


class TaskV2UpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    type: str | None = None
    status: str | None = None
    priority: str | None = None
    client_id: int | None = None
    project_id: int | None = None
    student_id: int | None = None
    assignee: str | None = None
    assignee_id: int | None = None
    goal: str | None = None
    result: str | None = None
    due_date: str | None = None
    execution_date: str | None = None
    deadline: str | None = None
    checklist: str | None = None
    tags: str | None = None
    source: str | None = None
    source_id: int | None = None
    completed_at: str | None = None


class ChecklistToggleBody(BaseModel):
    is_completed: bool = False


class TaskV2TableCommentBody(BaseModel):
    body: str = ""


class TaskV2CommentBody(BaseModel):
    text: str
    created_by: str | None = "owner"


class TaskAssignAgentBody(BaseModel):
    agent_name: str
    instruction: str | None = None


class TaskSendToTeamBody(BaseModel):
    task_mode: str | None = None
    agent_name: str | None = "chief_of_staff"


class EconomicsMonthUpdateBody(BaseModel):
    revenue_plan: float | None = None
    revenue_fact: float | None = None
    cash_received: float | None = None
    cash_expected: float | None = None
    expenses_marketing: float | None = None
    expenses_operating: float | None = None
    leads: int | None = None
    qualified_leads: int | None = None
    clients: int | None = None
    avg_check_override: float | None = None
    ltv: float | None = None
    notes: str | None = None


class IdeaCreateBody(BaseModel):
    title: str
    description: str | None = ""
    source: str | None = "owner"
    agent_name: str | None = ""
    status: str | None = "новая"
    tags: str | None = "[]"


class IdeaUpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: str | None = None


_KANBAN_PRIORITIES = frozenset({"низкий", "обычный", "высокий", "критично"})


class KanbanCreateBody(BaseModel):
    title: str
    content: str | None = ""
    column_id: str | None = "inbox"
    color: str | None = "default"
    tags: str | None = "[]"
    priority: str | None = "обычный"


class KanbanUpdateBody(BaseModel):
    title: str | None = None
    content: str | None = None
    column_id: str | None = None
    color: str | None = None
    position: int | None = None
    tags: str | None = None
    ai_summary: str | None = None
    due_date: str | None = None
    priority: str | None = None


class KanbanMoveBody(BaseModel):
    column_id: str | None = None
    direction: str | None = None  # next | prev


class KnowledgeDescBody(BaseModel):
    description: str


def _chunk_text(text: str, size: int = 1000) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _extract_text_from_upload(ext: str, raw: bytes) -> str:
    ext = ext.lower()
    if ext in (".txt", ".md", ".csv"):
        return raw.decode("utf-8", errors="replace")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception as e:
            logger.warning("PDF extract: %s", e)
            return ""
    if ext == ".docx":
        try:
            import docx

            d = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception as e:
            logger.warning("DOCX extract: %s", e)
            return ""
    if ext == ".xlsx":
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            lines = []
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    lines.append("\t".join(str(c) if c is not None else "" for c in row))
            return "\n".join(lines)
        except Exception as e:
            logger.warning("XLSX extract: %s", e)
            return ""
    return ""


async def _scan_notifications_v3() -> None:
    """Простые правила: просроченные tasks_v2, оплаты, health < 50."""
    today = date.today().isoformat()
    db_path = str(DB_PATH)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, title, due_date FROM tasks_v2
               WHERE status NOT IN ('готово', 'отменена') AND due_date != ''
               AND date(due_date) < date('now')"""
        )
        for row in await cur.fetchall():
            tid = row["id"]
            cur2 = await db.execute(
                "SELECT id FROM notifications WHERE type = ? AND entity_type = 'task_v2' AND entity_id = ?",
                ("дедлайн", tid),
            )
            if await cur2.fetchone():
                continue
            await db.execute(
                """INSERT INTO notifications (type, title, message, entity_type, entity_id, priority)
                   VALUES (?, ?, ?, 'task_v2', ?, 'высокий')""",
                ("дедлайн", f"Просрочена задача", row["title"] or "", tid),
            )
        cur = await db.execute(
            """SELECT id, client_id, amount, due_date FROM payments
               WHERE status NOT IN ('оплачено', 'возврат') AND due_date != ''
               AND date(due_date) < date('now')"""
        )
        for row in await cur.fetchall():
            pid = row["id"]
            cur2 = await db.execute(
                "SELECT id FROM notifications WHERE type = ? AND entity_type = 'payment' AND entity_id = ?",
                ("оплата", pid),
            )
            if await cur2.fetchone():
                continue
            await db.execute(
                """INSERT INTO notifications (type, title, message, entity_type, entity_id, priority)
                   VALUES (?, ?, ?, 'payment', ?, 'высокий')""",
                ("оплата", "Оплата не поступила", f"Счёт #{pid}, клиент {row['client_id']}", pid),
            )
        cur = await db.execute(
            "SELECT id, name, health_score FROM projects WHERE is_done = 0 AND health_score < 50"
        )
        for row in await cur.fetchall():
            pr = row["id"]
            cur2 = await db.execute(
                "SELECT id FROM notifications WHERE type = ? AND entity_type = 'project' AND entity_id = ?",
                ("риск", pr),
            )
            if await cur2.fetchone():
                continue
            await db.execute(
                """INSERT INTO notifications (type, title, message, entity_type, entity_id)
                   VALUES (?, ?, ?, 'project', ?)""",
                ("риск", "Низкий health проекта", row["name"] or f"Проект #{pr}", pr),
            )
        await db.commit()


def mount_hq_v3_routes(
    app: FastAPI,
    orchestrator: Any,
    verify_password: Callable[..., Any],
    hq_llm_run: Callable[[Any], Awaitable[Any]],
    require_role: Callable[..., Any],
    get_optional_hq_session: Callable[..., Any],
) -> None:
    """Регистрирует маршруты HQ v3 на переданном приложении."""

    # Canonical "Ожидается оплат" — единый источник истины для всех endpoint'ов.
    # Агентство: долг по клиентам (billable, не архив, total > 0).
    # Ученики: долг по полям student_total / student_paid (fallback на payment_*).
    BILLABLE_CLIENT_STATUSES = frozenset({
        s.strip().lower()
        for s in (
            "active", "done", "support", "paused",
            "Active", "Done", "Support",
            "активный", "завершён", "поддержка", "пауза",
        )
    })

    def _client_status_billable(raw: str | None) -> bool:
        return str(raw or "").strip().lower() in BILLABLE_CLIENT_STATUSES

    async def _sum_student_expected(conn: aiosqlite.Connection) -> float:
        total = 0.0
        try:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT status, student_total, student_paid, payment_total, payment_received
                   FROM students"""
            )
            rows = await cur.fetchall()
            for r in rows:
                st = str(r["status"] or "").strip().lower()
                if st in ("archived", "архив"):
                    continue
                st_tot = float(r["student_total"] if r["student_total"] is not None else 0)
                if st_tot <= 0:
                    st_tot = float(r["payment_total"] or 0)
                if st_tot <= 0:
                    continue
                st_paid = float(r["student_paid"] if r["student_paid"] is not None else 0)
                if st_paid <= 0 and float(r["payment_received"] or 0) > 0:
                    st_paid = float(r["payment_received"] or 0)
                total += max(0.0, st_tot - st_paid)
        except Exception:
            pass
        return total

    async def _canonical_expected_payments(
        clients: list[dict] | None = None,
        db: aiosqlite.Connection | None = None,
    ) -> dict[str, Any]:
        """Ожидаемые платежи: agency_expected / student_expected / total_expected."""
        if clients is None:
            clients = await get_clients()

        agency_expected = 0.0
        for c in clients:
            if int(c.get("is_archived") or 0) != 0:
                continue
            if not _client_status_billable(c.get("status")):
                continue
            ta = float(c.get("total_amount") or 0)
            if ta <= 0:
                continue
            pa = float(c.get("paid_amount") or 0)
            agency_expected += max(0.0, ta - pa)

        student_expected = 0.0
        if db is not None:
            student_expected = await _sum_student_expected(db)
        else:
            async with aiosqlite.connect(str(DB_PATH)) as inner:
                student_expected = await _sum_student_expected(inner)

        tot = agency_expected + student_expected
        return {
            "agency_expected": round(agency_expected, 2),
            "student_expected": round(student_expected, 2),
            "total_expected": round(tot, 2),
            "expected_payments": round(tot, 2),
        }

    async def _run_linked_team_task_background(
        task_v2_id: int,
        legacy_task_id: int,
        agent_name: str,
        message: str,
        task_mode: str | None,
    ) -> None:
        try:
            await orchestrator.run_task(message, task_id=legacy_task_id, task_mode=task_mode)
            legacy_task = await get_task(legacy_task_id)
            if not legacy_task:
                return
            result_text = (legacy_task.get("result") or legacy_task.get("error") or "").strip()
            assistant_message_id = None
            if result_text:
                assistant_message_id = await add_hq_message(agent_name, "assistant", result_text)
            await sync_task_v2_ai_link(
                task_v2_id,
                legacy_task_id=legacy_task_id,
                agent_name=agent_name,
                assistant_message_id=assistant_message_id,
                response_preview=result_text[:500] if result_text else "",
                status="готово" if legacy_task.get("status") == "done" else "в работе",
            )
            await insert_timeline_event(
                "task",
                task_v2_id,
                "агент",
                "Ответ AI-команды получен" if legacy_task.get("status") == "done" else "Задача ещё выполняется",
                result_text[:3000],
                {"legacy_task_id": legacy_task_id, "agent_name": agent_name},
                agent_name,
            )
        except Exception as exc:
            logger.error("linked team task failed: %s", exc, exc_info=True)
            await sync_task_v2_ai_link(
                task_v2_id,
                legacy_task_id=legacy_task_id,
                agent_name=agent_name,
                response_preview=str(exc),
                status="в работе",
            )

    @app.get("/api/clients/{client_id}/payments")
    async def v3_list_payments(
        client_id: int,
        _auth: bool = Depends(verify_password),
    ):
        if not await get_client(client_id):
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return {"payments": await list_payments_for_client(client_id)}

    @app.post("/api/clients/{client_id}/payments")
    async def v3_create_payment(
        client_id: int,
        payment: PaymentCreateBody,
        _session=Depends(require_role("owner")),
    ):
        if not await get_client(client_id):
            raise HTTPException(status_code=404, detail="Клиент не найден")
        pid = await insert_payment({**payment.model_dump(), "client_id": client_id})
        await recalc_client_paid_from_payments(client_id)
        await insert_timeline_event(
            "client",
            client_id,
            "оплата",
            "Платёж добавлен",
            json.dumps({"payment_id": pid, "amount": payment.amount}, ensure_ascii=False),
        )
        return {"id": pid}

    @app.put("/api/payments/{payment_id}")
    async def v3_update_payment(
        payment_id: int,
        payment: PaymentUpdateBody,
        _session=Depends(require_role("owner")),
    ):
        row = await get_payment(payment_id)
        if not row:
            raise HTTPException(status_code=404, detail="Платёж не найден")
        data = {k: v for k, v in payment.model_dump().items() if v is not None}
        await update_payment_row(payment_id, data)
        await recalc_client_paid_from_payments(int(row["client_id"]))
        return {"ok": True}

    @app.delete("/api/payments/{payment_id}")
    async def v3_delete_payment(payment_id: int, _session=Depends(require_role("owner"))):
        prev = await delete_payment_row(payment_id)
        if not prev:
            raise HTTPException(status_code=404, detail="Платёж не найден")
        await recalc_client_paid_from_payments(int(prev["client_id"]))
        return {"ok": True}

    @app.get("/api/timeline/{entity_type}/{entity_id}")
    async def v3_timeline_get(
        entity_type: str,
        entity_id: int,
        _auth: bool = Depends(verify_password),
    ):
        return {"events": await list_timeline_events(entity_type, entity_id)}

    @app.post("/api/timeline")
    async def v3_timeline_post(payload: TimelinePostBody, _session=Depends(require_role("owner", "pm"))):
        eid = await insert_timeline_event(
            payload.entity_type,
            payload.entity_id,
            payload.event_type,
            payload.title,
            payload.description or "",
            payload.meta,
            payload.created_by or "owner",
        )
        return {"id": eid}

    @app.get("/api/tasks-v2")
    async def v3_tasks_list(
        request: Request,
        status: str | None = Query(None),
        client_id: int | None = Query(None),
        priority: str | None = Query(None),
        project_id: int | None = Query(None),
        assignee: str | None = Query(None),
        execution_date: str | None = Query(None),
        month: str | None = Query(None),
        assignee_id: int | None = Query(None),
        my_tasks: bool = Query(False),
        _auth: bool = Depends(verify_password),
    ):
        sess = await get_optional_hq_session(request)
        uid_filter: int | None = None
        if sess and sess.get("role") == "executor":
            uid_filter = int(sess["user_id"])
        elif my_tasks and sess and sess.get("user_id") is not None:
            uid_filter = int(sess["user_id"])
        elif assignee_id is not None:
            uid_filter = assignee_id
        tasks_rows = await list_tasks_v2(
            status=status,
            client_id=client_id,
            priority=priority,
            project_id=project_id,
            assignee=assignee,
            execution_date=execution_date,
            month=month,
            assignee_user_id=uid_filter,
        )
        return {"tasks": tasks_rows}

    @app.post("/api/tasks-v2")
    async def v3_tasks_create(payload: TaskV2CreateBody, _session=Depends(require_role("owner", "pm"))):
        data = payload.model_dump()
        if not data.get("execution_date") and data.get("due_date"):
            data["execution_date"] = data.get("due_date")
        if not data.get("deadline") and data.get("due_date"):
            data["deadline"] = data.get("due_date")
        if not data.get("due_date"):
            data["due_date"] = data.get("deadline") or data.get("execution_date") or ""
        tid = await insert_task_v2(data)
        await insert_timeline_event(
            "task",
            tid,
            "задача",
            f"Создана задача: {payload.title}",
            created_by="owner",
        )
        return {"id": tid}

    @app.get("/api/tasks-v2/metrics")
    async def v3_tasks_metrics(
        request: Request,
        _auth: bool = Depends(verify_password),
    ):
        today = date.today().isoformat()
        sess = await get_optional_hq_session(request)
        uid = sess.get("user_id") if sess else None

        db_path = str(DB_PATH)
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM tasks_v2 WHERE status NOT IN ('готово','отменена')"
            )
            open_n = int((await cur.fetchone())[0])
            cur = await db.execute(
                """SELECT COUNT(*) FROM tasks_v2
                   WHERE status NOT IN ('готово','отменена')
                   AND date(COALESCE(NULLIF(execution_date,''), NULLIF(due_date,''))) = date(?)""",
                (today,),
            )
            today_n = int((await cur.fetchone())[0])
            cur = await db.execute(
                """SELECT COUNT(*) FROM tasks_v2
                   WHERE status NOT IN ('готово','отменена')
                   AND COALESCE(NULLIF(deadline,''), NULLIF(due_date,'')) != ''
                   AND date(COALESCE(NULLIF(deadline,''), NULLIF(due_date,''))) < date(?)""",
                (today,),
            )
            overdue_n = int((await cur.fetchone())[0])
            cur = await db.execute(
                """SELECT COUNT(*) FROM tasks_v2
                   WHERE assignee_id IS NOT NULL
                   AND status NOT IN ('готово','отменена')"""
            )
            team_n = int((await cur.fetchone())[0])
            my_n = 0
            if uid is not None:
                cur = await db.execute(
                    """SELECT COUNT(*) FROM tasks_v2
                       WHERE assignee_id=? AND status NOT IN ('готово','отменена')""",
                    (uid,),
                )
                my_n = int((await cur.fetchone())[0])

        return {
            "open": open_n,
            "today": today_n,
            "overdue": overdue_n,
            "in_team": team_n,
            "my": my_n,
        }

    @app.post("/api/tasks-v2/{tid}/checklist")
    async def v3_tasks_v2_checklist_add(
        tid: int,
        request: Request,
        _session=Depends(require_role("owner", "pm")),
    ):
        try:
            data = await request.json()
        except Exception:
            data = {}
        title = (data.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Название пункта обязательно")
        if not await get_task_v2(tid):
            raise HTTPException(status_code=404, detail="Задача не найдена")
        row = await insert_tasks_v2_checklist_item(tid, title)
        return row

    @app.put("/api/tasks-v2/checklist/{item_id}")
    async def v3_tasks_v2_checklist_toggle(
        item_id: int,
        body: ChecklistToggleBody,
        session: dict = Depends(require_role()),
    ):
        parent = await tasks_v2_checklist_task_id_for_item(item_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Пункт не найден")
        task = await get_task_v2(parent)
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        role = session.get("role")
        if role not in ("owner", "pm"):
            aid = task.get("assignee_id")
            uid = session.get("user_id")
            if aid is None or uid is None or int(aid) != int(uid):
                raise HTTPException(status_code=403, detail="Недостаточно прав")
        is_completed = 1 if body.is_completed else 0
        await update_tasks_v2_checklist_completed(item_id, is_completed)
        return {"success": True}

    @app.delete("/api/tasks-v2/checklist/{item_id}")
    async def v3_tasks_v2_checklist_del(
        item_id: int,
        _session=Depends(require_role("owner", "pm")),
    ):
        ok = await delete_tasks_v2_checklist_item(item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Пункт не найден")
        return {"success": True}

    @app.post("/api/tasks-v2/{tid}/comments")
    async def v3_tasks_v2_comments_add(
        tid: int,
        body: TaskV2TableCommentBody,
        session: dict = Depends(require_role()),
    ):
        text = (body.body or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Комментарий пустой")
        if not await get_task_v2(tid):
            raise HTTPException(status_code=404, detail="Задача не найдена")
        row = await insert_tasks_v2_comment(
            tid,
            session.get("user_id"),
            (session.get("name") or "").strip(),
            text,
        )
        return row

    @app.delete("/api/tasks-v2/comments/{cid}")
    async def v3_tasks_v2_comments_del(
        cid: int,
        _session=Depends(require_role("owner", "pm")),
    ):
        prev = await get_tasks_v2_comment(cid)
        if not prev:
            raise HTTPException(status_code=404, detail="Комментарий не найден")
        await delete_tasks_v2_comment(cid)
        return {"success": True}

    @app.get("/api/tasks-v2/{task_id}")
    async def v3_task_one(
        task_id: int,
        request: Request,
        _auth: bool = Depends(verify_password),
    ):
        sess = await get_optional_hq_session(request)
        row = await get_task_v2_detail(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        if sess and sess.get("role") == "executor":
            if row.get("assignee_id") != sess.get("user_id"):
                raise HTTPException(status_code=403, detail="Недоступно")
        row.pop("checklist_legacy_json", None)
        ev = await list_timeline_events("task", task_id)
        return {
            **row,
            "timeline": ev,
            "open_chat_url": (
                f"/hq/team.html?agent={row.get('ai_agent_name') or 'chief_of_staff'}&task={task_id}"
            ),
            "has_response": bool((row.get("response_preview") or "").strip()),
        }

    @app.put("/api/tasks-v2/{task_id}")
    async def v3_task_update(
        task_id: int,
        payload: TaskV2UpdateBody,
        session: dict = Depends(require_role()),
    ):
        task_row = await get_task_v2(task_id)
        if not task_row:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        raw = payload.model_dump(exclude_unset=True)
        role = session.get("role")

        exec_allowed = {
            "status",
            "result",
            "description",
            "goal",
            "due_date",
            "deadline",
            "execution_date",
            "priority",
        }
        if role == "executor":
            uid = session.get("user_id")
            if (
                task_row.get("assignee_id") is None
                or uid is None
                or int(task_row["assignee_id"]) != int(uid)
            ):
                raise HTTPException(status_code=403, detail="Недостаточно прав")
            data = {k: v for k, v in raw.items() if k in exec_allowed}
        elif role in ("owner", "pm"):
            data = dict(raw)
        else:
            raise HTTPException(status_code=403, detail="Недостаточно прав")

        if "execution_date" in data or "deadline" in data:
            data["due_date"] = data.get("deadline") or data.get("execution_date") or data.get(
                "due_date", ""
            )
        if not data:
            raise HTTPException(status_code=400, detail="Нет изменений")
        ok = await update_task_v2(task_id, data)
        if not ok:
            raise HTTPException(status_code=400, detail="Нет изменений")
        return {"ok": True}

    @app.delete("/api/tasks-v2/{task_id}")
    async def v3_task_delete(task_id: int, _session=Depends(require_role("owner", "pm"))):
        if not await delete_task_v2(task_id):
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return {"ok": True}

    @app.post("/api/tasks-v2/{task_id}/complete")
    async def v3_task_complete(task_id: int, _session=Depends(require_role("owner", "pm"))):
        if not await get_task_v2(task_id):
            raise HTTPException(status_code=404, detail="Задача не найдена")
        now = datetime.utcnow().isoformat()
        await update_task_v2(
            task_id,
            {"status": "готово", "completed_at": now},
        )
        await insert_timeline_event("task", task_id, "изменён", "Задача выполнена", created_by="owner")
        return {"ok": True}

    @app.post("/api/tasks-v2/{task_id}/send-to-team")
    async def v3_task_send_to_team(
        task_id: int,
        payload: TaskSendToTeamBody | None = None,
        _session=Depends(require_role("owner", "pm")),
    ):
        task = await get_task_v2(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        if task.get("ai_task_id"):
            return {
                "ok": True,
                "task_v2_id": task_id,
                "legacy_task_id": task.get("ai_task_id"),
                "open_chat_url": f"/hq/team.html?agent={task.get('ai_agent_name') or 'chief_of_staff'}&task={task_id}",
                "already_sent": True,
            }
        agent_name = ((payload.agent_name if payload else None) or "chief_of_staff").strip().lower().replace("-", "_")
        description = (task.get("description") or "").strip()
        text = f"{task.get('title')}\n\n{description}".strip()
        legacy_task_id = await db_create_owner_task(text)
        user_message_id = await add_hq_message(agent_name, "user", text)
        await sync_task_v2_ai_link(
            task_id,
            legacy_task_id=legacy_task_id,
            agent_name=agent_name,
            user_message_id=user_message_id,
            status="в работе",
        )
        await insert_timeline_event(
            "task",
            task_id,
            "агент",
            "Задача отправлена в AI-команду",
            "",
            {"legacy_task_id": legacy_task_id, "agent_name": agent_name},
            "owner",
        )
        asyncio.create_task(
            _run_linked_team_task_background(
                task_id,
                legacy_task_id,
                agent_name,
                text,
                payload.task_mode if payload else None,
            )
        )
        return {
            "ok": True,
            "task_v2_id": task_id,
            "legacy_task_id": legacy_task_id,
            "open_chat_url": f"/hq/team.html?agent={agent_name}&task={task_id}",
        }

    @app.post("/api/tasks-v2/{task_id}/comment")
    async def v3_task_comment(
        task_id: int,
        payload: TaskV2CommentBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        if not await get_task_v2(task_id):
            raise HTTPException(status_code=404, detail="Задача не найдена")
        t = await get_task_v2(task_id)
        n = int(t.get("comments_count") or 0) + 1
        await update_task_v2(task_id, {"comments_count": n})
        short = ((payload.text or "")[:120] or "Комментарий")
        await insert_timeline_event(
            "task",
            task_id,
            "комментарий",
            short,
            payload.text or "",
            None,
            payload.created_by or "owner",
        )
        return {"ok": True, "comments_count": n}

    @app.get("/api/team/tasks-history")
    async def v3_team_tasks_history(
        limit: int = Query(40, ge=1, le=200),
        _auth: bool = Depends(verify_password),
    ):
        return {"tasks": await get_team_tasks_history(limit=limit)}

    @app.get("/api/ideas")
    async def v3_ideas_list(_auth: bool = Depends(verify_password)):
        return {"ideas": await list_ideas()}

    @app.post("/api/ideas")
    async def v3_ideas_create(payload: IdeaCreateBody, _session=Depends(require_role("owner", "pm"))):
        iid = await insert_idea(payload.model_dump())
        await insert_notification("идея", "Новая идея", payload.title, "idea", iid)
        return {"id": iid}

    @app.put("/api/ideas/{idea_id}")
    async def v3_ideas_update(
        idea_id: int,
        payload: IdeaUpdateBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not await update_idea_row(idea_id, data):
            raise HTTPException(status_code=404, detail="Идея не найдена")
        return {"ok": True}

    @app.delete("/api/ideas/{idea_id}")
    async def v3_ideas_delete(idea_id: int, _session=Depends(require_role("owner", "pm"))):
        if not await delete_idea_row(idea_id):
            raise HTTPException(status_code=404, detail="Идея не найдена")
        return {"ok": True}

    @app.post("/api/ideas/{idea_id}/convert-to-task")
    async def v3_idea_to_task(idea_id: int, _session=Depends(require_role("owner", "pm"))):
        idea = await get_idea(idea_id)
        if not idea:
            raise HTTPException(status_code=404, detail="Идея не найдена")
        tid = await insert_task_v2(
            {
                "title": idea["title"],
                "description": idea.get("description") or "",
                "idea_id": idea_id,
                "status": "новая",
            }
        )
        await update_idea_row(idea_id, {"status": "в задаче", "task_id": tid})
        await insert_timeline_event(
            "task", tid, "задача", "Из идеи", "", {"idea_id": idea_id},
        )
        return {"task_id": tid}

    @app.get("/api/kanban")
    async def v3_kanban_list(_auth: bool = Depends(verify_password)):
        return {"notes": await list_kanban_notes()}

    @app.post("/api/kanban")
    async def v3_kanban_create(payload: KanbanCreateBody, _session=Depends(require_role("owner", "pm"))):
        raw = payload.model_dump()
        p = (raw.get("priority") or "обычный").strip().lower()
        if p == "критический":
            p = "критично"
        raw["priority"] = p if p in _KANBAN_PRIORITIES else "обычный"
        nid = await insert_kanban_note(raw)
        note = await get_kanban_note(nid)
        return note if note else {"id": nid}

    @app.put("/api/kanban/{note_id}")
    async def v3_kanban_update(
        note_id: int,
        payload: KanbanUpdateBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        if "priority" in data:
            p = (data["priority"] or "обычный").strip().lower()
            if p == "критический":
                p = "критично"
            data["priority"] = p if p in _KANBAN_PRIORITIES else "обычный"
        if not await update_kanban_note_row(note_id, data):
            raise HTTPException(status_code=404, detail="Заметка не найдена")
        return {"ok": True}

    @app.delete("/api/kanban/{note_id}")
    async def v3_kanban_delete(note_id: int, _session=Depends(require_role("owner", "pm"))):
        if not await delete_kanban_note_row(note_id):
            raise HTTPException(status_code=404, detail="Заметка не найдена")
        return {"ok": True}

    @app.post("/api/kanban/{note_id}/move")
    async def v3_kanban_move(
        note_id: int,
        payload: KanbanMoveBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        note = await get_kanban_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Заметка не найдена")
        # Порядок как на канбан-доске HQ: очередь → в работе → на проверке → готово
        cols = ["inbox", "doing", "archive", "done"]
        cur = (note.get("column_id") or "inbox").lower()
        if cur == "thinking":
            cur = "inbox"
        if cur not in cols:
            cur = "inbox"
        new_col: str | None = payload.column_id
        if payload.direction in ("next", "prev"):
            idx = cols.index(cur)
            if payload.direction == "next" and idx < len(cols) - 1:
                new_col = cols[idx + 1]
            elif payload.direction == "prev" and idx > 0:
                new_col = cols[idx - 1]
            else:
                new_col = cur
        if not new_col:
            raise HTTPException(status_code=400, detail="Укажите column_id или direction next/prev")
        await update_kanban_note_row(note_id, {"column_id": new_col})
        return {"success": True, "column_id": new_col, "ok": True}

    @app.post("/api/kanban/{note_id}/send-to-team")
    async def v3_kanban_send_to_team(
        note_id: int,
        _session=Depends(require_role("owner", "pm")),
    ):
        """Создать задачу AI-команде из карточки канбана (аналог owner_notes → команда)."""
        note = await get_kanban_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Карточка не найдена")
        title = (note.get("title") or "").strip()
        body = (note.get("content") or "").strip()
        if not title and not body:
            raise HTTPException(status_code=400, detail="Пустая карточка")
        msg = f"[Канбан HQ] {title}\n\n{body}".strip()
        task_id = await db_create_owner_task(msg)
        asyncio.create_task(orchestrator.run_task(msg, task_id=task_id))
        return {"success": True, "task_id": task_id, "message": "Задача принята командой"}

    @app.post("/api/kanban/{note_id}/ai-process")
    async def v3_kanban_ai(
        note_id: int,
        _session=Depends(require_role("owner", "pm")),
    ):
        note = await get_kanban_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Заметка не найдена")
        chief = orchestrator.team.chief
        col = (note.get("column_id") or "inbox").lower()
        pri = note.get("priority") or "обычный"
        prompt = (
            "Ты аналитик AI Delivery (агентство автоматизации для МСБ). "
            "Учти контекст канбана: колонка этапа и приоритет влияют на формулировки.\n"
            "Структурируй задачу владельца. Ответь строго JSON без markdown:\n"
            '{"summary":"краткое резюме 1-3 предложения","suggested_tasks":["конкретная подзадача"],'
            '"tags":["тег"],"suggested_priority":"низкий|обычный|высокий|критично"}\n'
            "suggested_priority — твоя оценка срочности с учётом текста и текущего приоритета.\n\n"
            f"Колонка канбана: {col}\n"
            f"Текущий приоритет: {pri}\n"
            f"Заголовок: {note.get('title')}\nТекст:\n{note.get('content') or ''}"
        )
        resp = await hq_llm_run(
            chief.think(prompt, context={"mode": "kanban_ai"}, task_id=None, max_tokens=2000, log_execution=False)
        )
        if not resp.success:
            raise HTTPException(status_code=500, detail=resp.error or "LLM")
        summary, tasks, tags = "", [], []
        suggested_priority: str | None = None
        try:
            m = re.search(r"\{[\s\S]*\}", resp.text)
            if m:
                d = json.loads(m.group())
                summary = str(d.get("summary") or "")
                tasks = list(d.get("suggested_tasks") or [])
                tags = list(d.get("tags") or [])
                sp = str(d.get("suggested_priority") or "").strip().lower()
                if sp == "критический":
                    sp = "критично"
                if sp in _KANBAN_PRIORITIES:
                    suggested_priority = sp
        except (json.JSONDecodeError, TypeError):
            summary = (resp.text or "")[:500]
        upd: dict = {"ai_summary": summary, "tags": json.dumps(tags, ensure_ascii=False)}
        if suggested_priority:
            upd["priority"] = suggested_priority
        await update_kanban_note_row(note_id, upd)
        invalidate_cache()
        return {
            "summary": summary,
            "suggested_tasks": tasks,
            "tags": tags,
            "suggested_priority": suggested_priority,
        }

    @app.get("/api/knowledge")
    async def v3_knowledge_list(_auth: bool = Depends(verify_password)):
        return {"files": await list_knowledge_rows()}

    @app.get("/api/knowledge/{kid}")
    async def v3_knowledge_one(kid: int, _auth: bool = Depends(verify_password)):
        row = await get_knowledge_row(kid)
        if not row:
            raise HTTPException(status_code=404, detail="Файл не найден")
        return dict(row)

    @app.post("/api/knowledge/upload")
    async def v3_knowledge_upload(
        file: UploadFile = File(...),
        _session=Depends(require_role("owner", "pm")),
    ):
        if not file.filename:
            raise HTTPException(status_code=400, detail="Файл не выбран")
        ext = Path(file.filename).suffix.lower()
        allowed = {".pdf", ".docx", ".txt", ".md", ".xlsx", ".csv"}
        if ext not in allowed:
            raise HTTPException(status_code=400, detail=f"Формат {ext} не поддерживается")
        raw = await file.read()
        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Файл слишком большой (макс 25 МБ)")
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = KNOWLEDGE_DIR / fname
        fpath.write_bytes(raw)
        text = _extract_text_from_upload(ext, raw)
        chunks = _chunk_text(text, 1000)
        chunks_j = json.dumps(chunks, ensure_ascii=False)
        st = "ready" if text.strip() else "ready"
        kid = await insert_knowledge_row(
            {
                "filename": fname,
                "original_name": file.filename,
                "file_type": ext.lstrip("."),
                "file_size": len(raw),
                "content_text": text,
                "chunks": chunks_j,
                "status": st,
                "description": "" if text.strip() else "Текст не извлечён — проверьте формат",
            }
        )
        invalidate_cache()
        return {"id": kid, "status": st, "chunks": len(chunks)}

    @app.delete("/api/knowledge/{kid}")
    async def v3_knowledge_delete(kid: int, _session=Depends(require_role("owner", "pm"))):
        row = await get_knowledge_row(kid)
        if not row:
            raise HTTPException(status_code=404, detail="Не найдено")
        fp = KNOWLEDGE_DIR / row["filename"]
        if fp.is_file():
            try:
                fp.unlink()
            except OSError:
                pass
        await delete_knowledge_row(kid)
        invalidate_cache()
        return {"ok": True}

    @app.get("/api/knowledge/search")
    async def v3_knowledge_search(
        q: str = Query(..., min_length=1),
        _auth: bool = Depends(verify_password),
    ):
        return {"results": await search_knowledge_simple(q)}

    @app.put("/api/knowledge/{kid}/description")
    async def v3_knowledge_desc(
        kid: int,
        payload: KnowledgeDescBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        if not await get_knowledge_row(kid):
            raise HTTPException(status_code=404, detail="Не найдено")
        await update_knowledge_row(kid, {"description": payload.description})
        invalidate_cache()
        return {"ok": True}

    @app.get("/api/analytics/revenue")
    async def v3_analytics_revenue(
        period: str = Query("month"),
        _auth: bool = Depends(verify_password),
    ):
        months = await list_economics_months(limit=24)
        return {
            "period": period,
            "series": [
                {
                    "month": row["month"],
                    "revenue": float(row.get("revenue_fact") or 0),
                    "received": float(row.get("cash_received") or 0),
                    "expected": float(row.get("cash_expected") or 0),
                }
                for row in reversed(months)
            ],
        }

    @app.get("/api/analytics/funnel")
    async def v3_analytics_funnel(_auth: bool = Depends(verify_password)):
        db_path = str(DB_PATH)
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT status, COUNT(*) FROM clients GROUP BY status"
            )
            by_s = {r[0]: r[1] for r in await cur.fetchall()}
        lead = int(by_s.get("lead", 0))
        active = int(by_s.get("active", 0))
        done = int(by_s.get("done", 0))
        total = max(1, lead + active + done)
        return {
            "lead": lead,
            "active": active,
            "done": done,
            "conversion_lead_active": round(active / max(1, lead + active), 4),
            "avg_days_placeholder": {
                "lead": 0,
                "active": 0,
                "done": 0,
            },
        }

    @app.get("/api/analytics/sources")
    async def v3_analytics_sources(_auth: bool = Depends(verify_password)):
        clients = await get_clients()
        by_src: dict[str, dict[str, float]] = {}
        for c in clients:
            src = (c.get("source") or "не указан").strip() or "не указан"
            if src not in by_src:
                by_src[src] = {"count": 0.0, "revenue": 0.0}
            by_src[src]["count"] += 1
            by_src[src]["revenue"] += float(c.get("paid_amount") or 0)
        rows = [
            {"source": k, "clients": int(v["count"]), "revenue": v["revenue"]}
            for k, v in sorted(by_src.items(), key=lambda x: -x[1]["revenue"])
        ]
        return {"sources": rows}

    @app.get("/api/analytics/pl")
    async def v3_analytics_pl(_auth: bool = Depends(verify_password)):
        months = await list_economics_months(limit=24)
        return {
            "months": [
                {
                    "month": row["month"],
                    "revenue": float(row.get("revenue_fact") or 0),
                    "expenses": float(row.get("total_expenses") or 0),
                    "profit": float(row.get("profit") or 0),
                    "margin_pct": float(row.get("margin") or 0),
                }
                for row in reversed(months)
            ]
        }

    @app.get("/api/analytics/kpi")
    async def v3_analytics_kpi(_auth: bool = Depends(verify_password)):
        bm = await get_business_metrics()
        db_path = str(DB_PATH)
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                """SELECT COUNT(*) FROM tasks_v2
                   WHERE status NOT IN ('готово', 'отменена')
                   AND COALESCE(NULLIF(deadline, ''), NULLIF(due_date, '')) != ''
                   AND date(COALESCE(NULLIF(deadline, ''), NULLIF(due_date, ''))) < date('now')"""
            )
            overdue_tasks = int((await cur.fetchone())[0])
        month = date.today().strftime("%Y-%m")
        economics = await get_economics_month(month)
        return {
            "cac": economics.get("cac", 0),
            "ltv": economics.get("ltv") or bm.get("ltv_active_avg", 0),
            "mrr": economics.get("revenue_fact", 0),
            "avg_check": economics.get("avg_check") or bm.get("avg_check", 0),
            "active_clients": bm.get("active_clients", 0),
            "active_students": bm.get("active_students", 0),
            "open_project_tasks": bm.get("open_tasks", 0),
            "overdue_tasks_v2": overdue_tasks,
            "lead_to_client_rate": bm.get("lead_to_client_rate", 0),
            "roi": economics.get("roi", 0),
            "romi": economics.get("romi", 0),
            "margin": economics.get("margin", 0),
        }

    @app.get("/api/analytics/overview")
    async def v3_analytics_overview(_auth: bool = Depends(verify_password)):
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        economics = await get_economics_month(today.strftime("%Y-%m"))
        db_path = str(DB_PATH)
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM clients")
            clients = [dict(r) for r in await cur.fetchall()]
            cur = await db.execute("SELECT * FROM projects")
            projects = [dict(r) for r in await cur.fetchall()]
            cur = await db.execute(
                """SELECT * FROM kanban_notes
                   WHERE due_date != '' AND date(due_date) < date(?)
                   AND column_id NOT IN ('done', 'archive')""",
                (today.isoformat(),),
            )
            overdue_notes = await cur.fetchall()
            cur = await db.execute("SELECT * FROM payments WHERE status != 'возврат'")
            payments = [dict(r) for r in await cur.fetchall()]

        active_clients = [c for c in clients if c.get("status") == "active"]
        leads = [c for c in clients if c.get("status") == "lead"]

        month_revenue = sum(
            float(p.get("amount") or 0)
            for p in payments
            if (p.get("paid_date") or "") >= month_start and p.get("status") == "оплачено"
        )

        done_clients = [c for c in clients if c.get("status") in ("done", "active")]
        avg_check = (
            sum(float(c.get("paid_amount") or 0) for c in done_clients) / len(done_clients)
            if done_clients
            else 0.0
        )

        total_ever = len(clients)
        converted = active_clients + [c for c in clients if c.get("status") == "done"]
        conversion = round(len(converted) / total_ever * 100) if total_ever else 0

        receivable = sum(
            max(0.0, float(c.get("total_amount") or 0) - float(c.get("paid_amount") or 0))
            for c in active_clients
            if float(c.get("total_amount") or 0) > float(c.get("paid_amount") or 0)
        )

        return {
            "month_revenue": economics.get("revenue_fact", month_revenue),
            "cash_received": economics.get("cash_received", 0),
            "cash_expected": economics.get("cash_expected", 0),
            "profit": economics.get("profit", 0),
            "margin": economics.get("margin", 0),
            "cac": economics.get("cac", 0),
            "ltv": economics.get("ltv", 0),
            "total_clients": len(clients),
            "active_clients": len(active_clients),
            "leads": len(leads),
            "qualified_leads": economics.get("qualified_leads", 0),
            "avg_check": round(economics.get("avg_check", avg_check)),
            "conversion": conversion,
            "lead_to_client": economics.get("lead_to_client", 0),
            "receivable": receivable,
            "overdue_tasks": len(overdue_notes),
            "active_projects": len([p for p in projects if not p.get("is_done")]),
            "overdue_projects": len(
                [
                    p
                    for p in projects
                    if p.get("deadline")
                    and str(p.get("deadline") or "")[:10] < today.isoformat()
                    and not p.get("is_done")
                ]
            ),
        }

    @app.get("/api/analytics/unit-economics")
    async def v3_unit_economics_get(
        month: str = Query(date.today().strftime("%Y-%m")),
        _auth: bool = Depends(verify_password),
    ):
        return {
            "month": month,
            "current": await get_economics_month(month),
            "history": await list_economics_months(limit=18),
        }

    @app.put("/api/analytics/unit-economics/{month}")
    async def v3_unit_economics_put(
        month: str,
        payload: EconomicsMonthUpdateBody,
        _session=Depends(require_role("owner")),
    ):
        return {
            "month": month,
            "current": await upsert_economics_month(
                month,
                {k: v for k, v in payload.model_dump().items() if v is not None},
            ),
            "history": await list_economics_months(limit=18),
        }

    @app.get("/api/dashboard/focus")
    async def v3_dashboard_focus(_auth: bool = Depends(verify_password)):
        today = date.today()
        tomorrow = today + timedelta(days=1)
        t_s, t_e = today.isoformat(), tomorrow.isoformat()
        t2 = (today + timedelta(days=2)).isoformat()
        tasks_all = await list_tasks_v2()
        overdue = [
            x for x in tasks_all
            if (x.get("deadline") or x.get("due_date")) and str(x.get("deadline") or x.get("due_date"))[:10] < t_s
            and x.get("status") not in ("готово", "отменена")
        ]
        due_today = [
            x for x in tasks_all
            if (x.get("execution_date") or x.get("due_date"))
            and t_s <= str(x.get("execution_date") or x.get("due_date"))[:10] < t_e
            and x.get("status") not in ("готово", "отменена")
        ]
        due_tmr = [
            x for x in tasks_all
            if (x.get("execution_date") or x.get("due_date"))
            and t_e <= str(x.get("execution_date") or x.get("due_date"))[:10] < t2
            and x.get("status") not in ("готово", "отменена")
        ]
        priority_today = [x for x in due_today if (x.get("priority") or "") == "критично"] + [
            x for x in due_today if (x.get("priority") or "") == "высокий"
        ]
        # Canonical: одна формула для всех endpoint'ов (см. _canonical_expected_payments)
        payments_focus = await _canonical_expected_payments()
        total_expected = payments_focus["total_expected"]
        return {
            "date": t_s,
            "overdue_tasks": overdue,
            "due_today": due_today,
            "due_tomorrow": due_tmr,
            "expected_payments_total": total_expected,
            "expected_payments": total_expected,
            "agency_expected": payments_focus["agency_expected"],
            "student_expected": payments_focus["student_expected"],
            "priority_today": priority_today[:20],
            "updated_at": datetime.utcnow().isoformat(),
        }

    @app.get("/api/dashboard/stats")
    async def v3_dashboard_stats(_auth: bool = Depends(verify_password)):
        bm = await get_business_metrics()
        economics = await get_economics_month(date.today().strftime("%Y-%m"))
        db_path = str(DB_PATH)
        today = date.today().isoformat()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COUNT(*) FROM tasks_v2 WHERE status NOT IN ('готово', 'отменена')"
            )
            open_v2 = int((await cur.fetchone())[0])
            cur = await db.execute(
                """SELECT COUNT(*) FROM tasks_v2
                   WHERE status NOT IN ('готово', 'отменена')
                   AND date(COALESCE(NULLIF(execution_date, ''), NULLIF(due_date, ''))) = date('now')"""
            )
            planned_today = int((await cur.fetchone())[0])
            all_clients = await get_clients()
            payments_data = await _canonical_expected_payments(all_clients, db)

        debtors = []
        for c in all_clients:
            total = float(c.get("total_amount") or 0)
            paid = float(c.get("paid_amount") or 0)
            if total > paid and _client_status_billable(c.get("status")):
                debtors.append({
                    "id": c["id"],
                    "name": c.get("name"),
                    "company": c.get("company"),
                    "total_amount": total,
                    "paid_amount": paid,
                    "debt": round(total - paid, 2),
                })
        debtors.sort(key=lambda x: x["debt"], reverse=True)
        canonical_expected = payments_data["total_expected"]
        agency_expected = payments_data["agency_expected"]
        student_expected = payments_data["student_expected"]
        # Полученные средства: из payments (status='оплачено') или fallback на bm.total_paid
        received_total = float(bm.get("total_paid") or 0)
        econ_received = float(economics.get("cash_received") or 0)
        real_received = max(received_total, econ_received)
        return {
            "active_clients": bm.get("active_clients", 0),
            "active_students": bm.get("active_students", 0),
            "open_tasks_v2": open_v2,
            "tasks_today": planned_today,
            "revenue_paid_total": round(real_received, 2),
            "pending_payments_total": canonical_expected,
            "expected_payments": canonical_expected,
            "agency_expected": agency_expected,
            "student_expected": student_expected,
            "mrr_estimate": round(float(economics.get("revenue_fact") or 0), 2),
            "debtors": debtors[:20],
            "debtors_total": canonical_expected,
            "date": today,
        }

    @app.get("/api/finance/summary")
    async def v3_finance_summary(_auth: bool = Depends(verify_password)):
        """Полная финансовая сводка: агентство, ученики, процент с проектов, расходы."""
        db_path = str(DB_PATH)

        agency_contracted = 0.0
        agency_received = 0.0
        agency_expected = 0.0
        student_contracted = 0.0
        student_received = 0.0
        student_expected = 0.0
        percent_received = 0.0
        percent_expected_total = 0.0
        percent_total_contract = 0.0
        percent_rows_list: list[aiosqlite.Row] = []
        expenses_total = 0.0
        expenses_paid = 0.0

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            cur = await db.execute(
                """SELECT total_amount, paid_amount, status
                   FROM clients
                   WHERE COALESCE(is_archived, 0) = 0"""
            )
            for c in await cur.fetchall():
                if not _client_status_billable(c["status"]):
                    continue
                ta = float(c["total_amount"] or 0)
                pa = float(c["paid_amount"] or 0)
                agency_received += pa
                if ta > 0:
                    agency_expected += max(0.0, ta - pa)
                agency_contracted += ta

            cur = await db.execute(
                """SELECT student_total, student_paid, revenue_type, status,
                          payment_total, payment_received
                   FROM students"""
            )
            studs = await cur.fetchall()
            for s in studs:
                if str(s["status"] or "").strip().lower() in ("archived", "архив"):
                    continue
                tot = float(s["student_total"] if s["student_total"] is not None else 0)
                if tot <= 0:
                    tot = float(s["payment_total"] or 0)
                paid_here = float(s["student_paid"] if s["student_paid"] is not None else 0)
                if paid_here <= 0 and float(s["payment_received"] or 0) > 0:
                    paid_here = float(s["payment_received"] or 0)
                student_contracted += tot
                if tot > 0:
                    student_received += paid_here
                    student_expected += max(0.0, tot - paid_here)

            try:
                cur = await db.execute("SELECT our_amount, paid_amount FROM student_projects")
                percent_rows_list = await cur.fetchall()
            except Exception:
                percent_rows_list = []

            for r in percent_rows_list:
                oa = float(r["our_amount"] or 0)
                pa_amt = float(r["paid_amount"] or 0)
                percent_total_contract += oa
                percent_received += pa_amt
                percent_expected_total += max(0.0, oa - pa_amt)

            try:
                cur = await db.execute("SELECT amount, paid FROM student_expenses")
                ex_rows = await cur.fetchall()
            except Exception:
                ex_rows = []
            for r in ex_rows:
                amt = float(r["amount"] or 0)
                expenses_total += amt
                if r["paid"]:
                    expenses_paid += amt

        return {
            "agency": {
                "contracted": round(agency_contracted, 2),
                "received": round(agency_received, 2),
                "expected": round(agency_expected, 2),
                "label": "Выручка агентства",
            },
            "students": {
                "contracted": round(student_contracted, 2),
                "received": round(student_received, 2),
                "expected": round(student_expected, 2),
                "label": "Доход с учеников",
            },
            "percent": {
                "total_amount": round(percent_total_contract, 2),
                "received": round(percent_received, 2),
                "expected": round(percent_expected_total, 2),
                "label": "Процент с проектов",
            },
            "expenses": {
                "total": round(expenses_total, 2),
                "paid": round(expenses_paid, 2),
                "pending": round(expenses_total - expenses_paid, 2),
                "label": "Расходы на учеников",
            },
            "total": {
                "received": round(
                    agency_received + student_received + percent_received,
                    2,
                ),
                "expected": round(
                    agency_expected + student_expected + percent_expected_total,
                    2,
                ),
                "net": round(
                    agency_received + student_received + percent_received - expenses_paid,
                    2,
                ),
                "label": "Итого",
            },
        }

    @app.get("/api/search")
    async def v3_global_search(
        q: str = Query(""),
        _auth: bool = Depends(verify_password),
    ):
        qq = (q or "").strip()
        if len(qq) < 2:
            return []
        out: list[dict] = []
        for c in await get_clients():
            if qq.lower() in (c.get("name") or "").lower() or qq.lower() in (c.get("company") or "").lower():
                out.append({
                    "type": "client",
                    "id": c["id"],
                    "title": c.get("name") or "Клиент",
                    "preview": (c.get("company") or "")[:120],
                    "url": f"/hq/crm.html#c{c['id']}",
                })
        for p in await get_projects():
            if qq.lower() in (p.get("name") or "").lower():
                out.append({
                    "type": "project",
                    "id": p["id"],
                    "title": p.get("name") or "Проект",
                    "preview": p.get("client_name") or "",
                    "url": "/hq/crm.html",
                })
        for t in await list_tasks_v2():
            if qq.lower() in (t.get("title") or "").lower():
                out.append({
                    "type": "task",
                    "id": t["id"],
                    "title": t.get("title") or "Задача",
                    "preview": (t.get("description") or "")[:120],
                    "url": "/hq/tasks.html",
                })
        for n in await list_kanban_notes():
            if qq.lower() in (n.get("title") or "").lower() or qq.lower() in (n.get("content") or "").lower():
                out.append({
                    "type": "note",
                    "id": n["id"],
                    "title": n.get("title") or "Заметка",
                    "preview": (n.get("content") or "")[:80],
                    "url": "/hq/notes.html",
                })
        for row in await search_knowledge_simple(qq, limit=10):
            out.append({
                "type": "knowledge",
                "id": row["id"],
                "title": row.get("original_name") or "Файл",
                "preview": (row.get("preview") or "")[:120],
                "url": "/hq/knowledge.html",
            })
        for s in await get_students():
            if qq.lower() in (s.get("name") or "").lower():
                out.append({
                    "type": "student",
                    "id": s["id"],
                    "title": s.get("name") or "Ученик",
                    "preview": s.get("program") or "",
                    "url": "/hq/crm.html",
                })
        return out[:80]

    @app.get("/api/notifications")
    async def v3_notif_list(
        unread: bool = Query(False),
        _auth: bool = Depends(verify_password),
    ):
        await _scan_notifications_v3()
        return {"notifications": await list_notifications(unread_only=unread, limit=100)}

    @app.post("/api/notifications/{nid}/read")
    async def v3_notif_read(nid: int, _auth: bool = Depends(verify_password)):
        if not await mark_notification_read(nid):
            raise HTTPException(status_code=404, detail="Нет")
        return {"ok": True}

    @app.post("/api/notifications/read-all")
    async def v3_notif_read_all(_auth: bool = Depends(verify_password)):
        await mark_all_notifications_read()
        return {"ok": True}

    @app.get("/api/notifications/count")
    async def v3_notif_count(_auth: bool = Depends(verify_password)):
        await _scan_notifications_v3()
        return {"count": await count_unread_notifications()}

    @app.post("/api/tasks-v2/{task_id}/assign-agent")
    async def v3_task_assign_agent(
        task_id: int,
        payload: TaskAssignAgentBody,
        _session=Depends(require_role("owner", "pm")),
    ):
        task = await get_task_v2(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        name = payload.agent_name.strip().lower().replace("-", "_")
        agent = orchestrator.team.get(name)
        if not agent:
            raise HTTPException(status_code=404, detail="Агент не найден")
        brief = (
            f"Задача HQ (tasks_v2 #{task_id}): {task.get('title')}\n"
            f"Описание: {task.get('description') or '—'}\n"
            f"Инструкция владельца: {payload.instruction or 'Выполни задачу и дай результат.'}"
        )
        resp = await hq_llm_run(
            agent.think(brief, context={"hq_task_v2_id": task_id}, task_id=None, max_tokens=6000, log_execution=False)
        )
        if not resp.success:
            raise HTTPException(status_code=500, detail=resp.error or "LLM")
        text = (resp.text or "")[:15000]
        t = await get_task_v2(task_id)
        n = int(t.get("comments_count") or 0) + 1 if t else 1
        await update_task_v2(task_id, {"comments_count": n})
        await insert_timeline_event(
            "task",
            task_id,
            "агент",
            f"Ответ агента {name}",
            text,
            None,
            name,
        )
        return {"ok": True, "text": resp.text, "comments_count": n}
