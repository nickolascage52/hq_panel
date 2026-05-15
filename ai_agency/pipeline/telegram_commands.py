"""Telegram pipeline commands (v1.2 — owner can manage runs from phone).

Extension module — does NOT modify telegram_bot.py logic, only adds new
command handlers via register_pipeline_commands(app_builder).

Commands added:
- /pipelines             — list runs (default: active + recent)
- /run <id>              — show run details + last events
- /approve <id>          — approve awaiting_approval run
- /pause <id>            — pause running run
- /resume <id>           — resume paused run
- /abort <id>            — abort run

All commands gated by TELEGRAM_OWNER_ID — only owner can manage pipeline.
Other users get a polite 'not authorized' reply.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)


def _is_owner(update_user_id: int | None) -> bool:
    owner_id = os.getenv("TELEGRAM_OWNER_ID", "0")
    try:
        return update_user_id is not None and int(owner_id) == int(update_user_id)
    except (ValueError, TypeError):
        return False


def _format_run_summary(run: dict[str, Any]) -> str:
    status = run.get("status", "?")
    phase = run.get("current_phase") or "—"
    tokens = run.get("tokens_used") or 0
    return (
        f"#{run['id']} [{status}] {run.get('title', '(no title)')[:40]}\n"
        f"   📊 phase: {phase} · 🪙 {tokens} tokens"
    )


async def _fetch_runs(limit: int = 10, status: str | None = None) -> list[dict]:
    sql = "SELECT id, title, status, current_phase, tokens_used FROM pipeline_runs"
    vals: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        vals.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    vals.append(limit)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, vals)
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _fetch_run(run_id: int) -> dict | None:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def _fetch_recent_events(run_id: int, limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT event_type, severity, payload_json, created_at "
            "FROM pipeline_events WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (run_id, limit),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _change_run_status(run_id: int, new_status: str, **fields) -> bool:
    sets = ["status = ?"]
    vals: list[Any] = [new_status]
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        vals.append(v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else v)
    vals.append(run_id)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?", vals,
        )
        await db.commit()
        return (cur.rowcount or 0) > 0


# ── Command handlers ────────────────────────────────────────────────────


async def _cmd_pipelines(update, context):
    if not _is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔ Эта команда только для владельца.")
        return
    runs = await _fetch_runs(limit=10)
    if not runs:
        await update.message.reply_text("Pipeline-runs нет.")
        return
    body = "\n\n".join(_format_run_summary(r) for r in runs)
    await update.message.reply_text(f"🤖 Pipeline runs (последние 10):\n\n{body}")


async def _cmd_run(update, context):
    if not _is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔ Только для владельца.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /run <id>")
        return
    try:
        run_id = int(context.args[0])
    except (ValueError, IndexError):
        await update.message.reply_text("ID должен быть числом.")
        return
    run = await _fetch_run(run_id)
    if not run:
        await update.message.reply_text(f"Run #{run_id} не найден.")
        return
    events = await _fetch_recent_events(run_id, limit=5)
    events_str = "\n".join(
        f"  · {e['event_type']} ({e['created_at']})" for e in events
    ) or "  (нет событий)"
    body = (
        f"🤖 Pipeline #{run_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Title: {run.get('title', '—')}\n"
        f"Type: {run.get('project_type', '—')}\n"
        f"Status: {run.get('status', '—')}\n"
        f"Phase: {run.get('current_phase') or '—'}\n"
        f"Autonomy: {run.get('autonomy_level', '—')}\n"
        f"Deploy: {run.get('deploy_strategy', '—')}\n"
        f"Tokens: {run.get('tokens_used') or 0}\n"
        f"Created: {run.get('created_at', '—')}\n"
        f"{('Error: ' + run['error_message']) if run.get('error_message') else ''}"
        f"\n\nПоследние события:\n{events_str}"
    )
    await update.message.reply_text(body)


async def _action_command(update, context, action: str):
    """Shared logic for /approve, /pause, /resume, /abort."""
    if not _is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔ Только для владельца.")
        return
    if not context.args:
        await update.message.reply_text(f"Использование: /{action} <id>")
        return
    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    run = await _fetch_run(run_id)
    if not run:
        await update.message.reply_text(f"Run #{run_id} не найден.")
        return
    current = run["status"]

    # Validate transition (mirror pipeline_api.py rules)
    if action == "approve" and current != "awaiting_approval":
        await update.message.reply_text(f"❌ Нельзя approve: status='{current}' (ожидался 'awaiting_approval').")
        return
    if action == "pause" and current not in ("running", "pending"):
        await update.message.reply_text(f"❌ Нельзя pause: status='{current}'.")
        return
    if action == "resume" and current not in ("paused_user", "paused_rate_limit", "awaiting_approval"):
        await update.message.reply_text(f"❌ Нельзя resume: status='{current}'.")
        return
    if action == "abort" and current in ("done", "aborted", "failed"):
        await update.message.reply_text(f"❌ Нельзя abort: статус уже terminal ('{current}').")
        return

    # Apply
    from .progress import PipelineProgress
    from .runner import PipelineRunner
    from .audit import log_action

    progress = PipelineProgress(run_id)
    actor_id = update.effective_user.id if update.effective_user else None

    if action == "pause":
        await _change_run_status(run_id, "paused_user",
                                 paused_at=datetime.now(),
                                 pause_reason="manual pause by owner (via Telegram)")
        await progress.emit_event("paused", payload={"reason": "manual_telegram"}, severity="warning")
        await log_action(run_id=run_id, action="pause", actor="telegram_owner",
                         actor_id=actor_id, source="telegram",
                         from_status=current, to_status="paused_user")
        await update.message.reply_text(f"⏸ Pipeline #{run_id} → paused")
    elif action in ("resume", "approve"):
        await progress.emit_event(
            "approval_granted" if action == "approve" else "resumed",
            payload={"by": "telegram_owner", "from_status": current},
        )
        await log_action(run_id=run_id, action=action, actor="telegram_owner",
                         actor_id=actor_id, source="telegram",
                         from_status=current, to_status="running")
        # Spawn resume in background
        asyncio.create_task(PipelineRunner(run_id).resume())
        verb = "одобрен" if action == "approve" else "возобновлён"
        await update.message.reply_text(f"✅ Pipeline #{run_id} {verb} → running")
    elif action == "abort":
        await _change_run_status(run_id, "aborted",
                                 completed_at=datetime.now(),
                                 error_message=f"aborted by owner (via Telegram, was {current})")
        await progress.emit_event("run_aborted", payload={"by": "telegram_owner", "from_status": current},
                                  severity="warning")
        await log_action(run_id=run_id, action="abort", actor="telegram_owner",
                         actor_id=actor_id, source="telegram",
                         from_status=current, to_status="aborted")
        await update.message.reply_text(f"❌ Pipeline #{run_id} aborted")


async def _cmd_approve(update, context):
    await _action_command(update, context, "approve")


async def _cmd_pause(update, context):
    await _action_command(update, context, "pause")


async def _cmd_resume(update, context):
    await _action_command(update, context, "resume")


async def _cmd_abort(update, context):
    await _action_command(update, context, "abort")


# ── Public API ──────────────────────────────────────────────────────────


def register_pipeline_commands(app_builder) -> None:
    """Register pipeline commands on a python-telegram-bot Application.

    Called from telegram_bot.py:create_bot_application() after existing
    handlers are added. Adds 6 new commands without touching existing logic.

    Args:
        app_builder: telegram.ext.Application instance with .add_handler().
    """
    try:
        from telegram.ext import CommandHandler  # type: ignore
    except ImportError:
        logger.warning("python-telegram-bot not available — pipeline TG commands skipped")
        return

    app_builder.add_handler(CommandHandler("pipelines", _cmd_pipelines))
    app_builder.add_handler(CommandHandler("run", _cmd_run))
    app_builder.add_handler(CommandHandler("approve", _cmd_approve))
    app_builder.add_handler(CommandHandler("pause", _cmd_pause))
    app_builder.add_handler(CommandHandler("resume", _cmd_resume))
    app_builder.add_handler(CommandHandler("abort", _cmd_abort))
    logger.info("Pipeline Telegram commands registered: "
                "/pipelines /run /approve /pause /resume /abort")
