"""
Telegram-бот для управления AI-командой.
python-telegram-bot v21 (async).
Только владелец (TELEGRAM_OWNER_ID) может управлять системой.
"""

from __future__ import annotations

import logging
import os
import asyncio
import re
import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from telegram import InputFile, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from database import (
    create_task,
    get_metrics,
    get_task,
    get_task_chain,
    get_content_by_id,
    update_content_status,
    get_tasks,
    get_content,
    get_content_for_task,
    save_daily_report,
    list_tasks_v2,
    insert_task_v2,
    insert_timeline_event,
    list_ideas,
    get_business_metrics,
    DB_PATH,
    format_focus_brief_text,
)
from orchestrator import Orchestrator
from agents.team import AgencyTeam
from agents.request_context import telegram_llm_mode
from hq_snapshot import build_account_snapshot_json

logger = logging.getLogger("telegram_bot")

OWNER_ID: int | None = None
orchestrator_instance: Orchestrator | None = None

ENV_PATH = Path(__file__).resolve().parent / ".env"
AGENT_COUNT = len(AgencyTeam().list_agents())
TASK_MODES = ("lite", "standard", "full")


def get_owner_id() -> int:
    global OWNER_ID
    if OWNER_ID is None:
        raw = os.getenv("TELEGRAM_OWNER_ID", "0")
        OWNER_ID = int(raw)
    return OWNER_ID


def is_owner(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == get_owner_id()


def set_orchestrator(orch: Orchestrator):
    global orchestrator_instance
    orchestrator_instance = orch


def get_orchestrator() -> Orchestrator:
    global orchestrator_instance
    if orchestrator_instance is None:
        orchestrator_instance = Orchestrator()
    return orchestrator_instance


async def _with_telegram_llm(coro):
    """Все вызовы LLM из Telegram — max_tokens 4000 (см. AgentBase.think + telegram_llm_mode)."""
    tok = telegram_llm_mode.set(True)
    try:
        return await coro
    finally:
        telegram_llm_mode.reset(tok)


async def _account_manager_telegram_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    instruction: str,
    save_daily: bool = False,
) -> None:
    orch = get_orchestrator()
    snap = await build_account_snapshot_json()
    user_msg = f"{instruction}\n\nДАННЫЕ ИЗ БД (JSON):\n{snap}"
    await owner_reply_chunks(update, context, "⏳ Аккаунт-менеджер готовит ответ…")
    resp = await _with_telegram_llm(
        orch.team.account_manager.think(
            user_msg,
            context={"source": "telegram"},
            task_id=None,
            max_tokens=8000,
            log_execution=False,
        )
    )
    if not resp.success:
        await split_and_send(update, f"❌ {resp.error}", context)
        await send_main_menu(context, update.effective_chat.id)
        return
    if save_daily:
        payload = json.dumps(
            {"text": resp.text, "generated_at": datetime.utcnow().isoformat()},
            ensure_ascii=False,
        )
        await save_daily_report(date.today().isoformat(), payload)
    await split_and_send(update, resp.text, context)
    await send_main_menu(context, update.effective_chat.id)


def get_default_task_mode() -> str:
    m = (os.getenv("DEFAULT_TASK_MODE") or "lite").strip().lower()
    return m if m in TASK_MODES else "lite"


def is_auto_publish_on() -> bool:
    return os.getenv("AUTO_PUBLISH", "false").strip().lower() in ("1", "true", "yes", "on")


def format_env_value(value: str) -> str:
    if re.search(r'[\s"#\']', value) or value == "":
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def update_env_file(key: str, value: str) -> None:
    """Перезаписать или добавить ключ в .env (UTF-8), обновить os.environ."""
    display = format_env_value(value) if key == "ADMIN_PASSWORD" else value
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    found = False
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        k = s.split("=", 1)[0].strip()
        if k == key:
            new_lines.append(f"{key}={display}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={display}")

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def cycle_task_mode() -> str:
    current = get_default_task_mode()
    i = TASK_MODES.index(current) if current in TASK_MODES else 0
    nxt = TASK_MODES[(i + 1) % len(TASK_MODES)]
    update_env_file("DEFAULT_TASK_MODE", nxt)
    return nxt


def toggle_auto_publish() -> bool:
    new_val = "false" if is_auto_publish_on() else "true"
    update_env_file("AUTO_PUBLISH", new_val)
    return is_auto_publish_on()


def clean_for_telegram(text: str) -> str:
    """Убирает markdown, оставляет только эмодзи и текст."""
    # Убираем ## заголовки — оставляем текст
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Убираем **жирный** — оставляем текст
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Убираем *курсив* — оставляем текст
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # Убираем --- разделители
    text = re.sub(r"^[-─━]{3,}.*$", "──────────", text, flags=re.MULTILINE)
    # Убираем ``` блоки кода
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Убираем одиночные backtick
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Убираем > цитаты
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # Убираем лишние пустые строки (больше 2 подряд)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_message(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        cut = text.rfind("\n\n", 0, max_len)
        if cut == -1:
            cut = text.rfind(". ", 0, max_len)
        if cut == -1:
            cut = max_len
        if cut <= 0:
            cut = max_len
        chunk = text[:cut].strip()
        if not chunk:
            cut = min(max_len, len(text))
            chunk = text[:cut]
        parts.append(chunk.strip())
        text = text[cut:].strip()
    return parts


def get_outgoing_chunks(text: str, max_len: int = 4000) -> list[str]:
    """Очистка + разбиение по max_len символов; продолжения с пометкой 📄 Продолжение [i/n]."""
    cleaned = clean_for_telegram(text)
    if not cleaned:
        cleaned = "—"
    parts = split_message(cleaned, max_len)
    if len(parts) <= 1:
        return parts
    n = len(parts)
    out = [parts[0]]
    for i in range(1, n):
        out.append(f"📄 Продолжение [{i + 1}/{n}]:\n\n{parts[i]}")
    return out


async def send_messages_cleaned(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    reply_to_message_id: int | None = None,
) -> None:
    """Отправка в чат: clean_for_telegram + split_message для длинных текстов."""
    parts = get_outgoing_chunks(text)
    for i, part in enumerate(parts):
        kw: dict = {}
        if i == len(parts) - 1 and reply_markup is not None:
            kw["reply_markup"] = reply_markup
        if i == 0 and reply_to_message_id is not None:
            kw["reply_to_message_id"] = reply_to_message_id
        await context.bot.send_message(chat_id=chat_id, text=part, **kw)


async def owner_reply_chunks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Ответ на сообщение владельца: первая часть — reply, остальные — в чат."""
    chat_id = update.effective_chat.id
    parts = get_outgoing_chunks(text)
    for i, part in enumerate(parts):
        kw: dict = {}
        if i == len(parts) - 1 and reply_markup is not None:
            kw["reply_markup"] = reply_markup
        if i == 0 and update.message:
            await update.message.reply_text(part, **kw)
        else:
            await context.bot.send_message(chat_id=chat_id, text=part, **kw)


# ── Клавиатуры ──


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Отчёт дня", callback_data="am_report"),
                InlineKeyboardButton("👥 Клиенты", callback_data="am_clients"),
            ],
            [
                InlineKeyboardButton("🎓 Ученики", callback_data="am_students"),
                InlineKeyboardButton("💰 Финансы", callback_data="am_finance"),
            ],
            [
                InlineKeyboardButton("📅 Дедлайны", callback_data="am_deadlines"),
                InlineKeyboardButton("🤖 Команда", callback_data="m_new"),
            ],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="m_set")],
            [
                InlineKeyboardButton("📊 Статус системы", callback_data="m_status"),
                InlineKeyboardButton("📋 История задач", callback_data="m_hist"),
            ],
            [InlineKeyboardButton("✏️ Контент на одобрение", callback_data="m_cont")],
        ]
    )


def post_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Переделать", callback_data=f"tredo_{task_id}"),
                InlineKeyboardButton("✅ Принять", callback_data=f"tok_{task_id}"),
            ],
            [
                InlineKeyboardButton("📤 Опубликовать в Telegram", callback_data=f"tpub_{task_id}"),
                InlineKeyboardButton("💾 Сохранить", callback_data=f"tsv_{task_id}"),
            ],
            [InlineKeyboardButton("🚀 Новый запрос", callback_data="m_new")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="m_main")],
        ]
    )


def client_analysis_followup_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🤝 Сгенерировать КП", callback_data=f"ckp_{task_id}")],
            [InlineKeyboardButton("💬 Брейншторм", callback_data=f"cbs_{task_id}")],
            [
                InlineKeyboardButton("🔄 Пересмотреть решение", callback_data=f"credo_{task_id}"),
                InlineKeyboardButton("📋 Новый клиент", callback_data="cnewc"),
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="m_main")],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    mode = get_default_task_mode().upper()
    pub = is_auto_publish_on()
    pub_lbl = "📢 Автопостинг: ВКЛ" if pub else "📢 Автопостинг: ВЫКЛ"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🔋 Режим: {mode}", callback_data="set_mode")],
            [InlineKeyboardButton(pub_lbl, callback_data="set_pub")],
            [InlineKeyboardButton("🔑 Сменить пароль панели", callback_data="set_pw")],
            [InlineKeyboardButton("ℹ️ О системе", callback_data="set_about")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="m_main")],
        ]
    )


def content_item_keyboard(cid: int) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("👁 Посмотреть", callback_data=f"cv_{cid}"),
        InlineKeyboardButton("✅ Одобрить", callback_data=f"ca_{cid}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"cr_{cid}"),
    ]


async def send_main_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    prefix: str | None = None,
):
    text = (prefix + "\n\n") if prefix else ""
    text += "──────────────\n🏠 Главное меню"
    await send_messages_cleaned(
        context,
        chat_id,
        text,
        reply_markup=main_menu_keyboard(),
    )


async def split_and_send(
    update_or_chat,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
):
    """Длинные ответы: clean_for_telegram + split_message (~3800), нумерация частей."""
    _ = parse_mode  # совместимость вызовов; форматирование — plain после очистки
    chat_id = (
        update_or_chat.effective_chat.id
        if hasattr(update_or_chat, "effective_chat")
        else update_or_chat
    )
    reply_to_message_id = None
    if hasattr(update_or_chat, "message") and update_or_chat.message:
        reply_to_message_id = update_or_chat.message.message_id
    await send_messages_cleaned(
        context,
        chat_id,
        text,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )


# ── Команды ──


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return

    text = (
        "🤖 AI Agency Management System\n\n"
        "Управление командой из {n} агентов.\n"
        "Напиши задачу текстом или нажми «Новый запрос».\n\n"
        "Примеры:\n"
        "• Пост в Telegram про чат-ботов\n"
        "• Анализ конкурентов в нише ИИ-ботов\n"
        "• Новый оффер для сайта\n"
        "• Аудит главной страницы\n\n"
        "Аккаунт: /report /clients /students /finance /deadlines\n"
        "Прямой агент: /agent имя сообщение\n"
        "Остальное: /client /task /approve_kp /brainstorm /status /content /help"
    ).format(n=AGENT_COUNT)

    await owner_reply_chunks(
        update,
        context,
        text,
        reply_markup=main_menu_keyboard(),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    context.user_data.pop("awaiting_admin_password", None)
    await owner_reply_chunks(update, context, "Отменено.")
    await send_main_menu(context, update.effective_chat.id)


async def cmd_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    if not context.args:
        await owner_reply_chunks(
            update,
            context,
            "Использование: /client описание ситуации клиента",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    text = " ".join(context.args).strip()
    await _run_client_analysis_chat(update, context, text)


async def cmd_approve_kp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    tid = context.user_data.get("last_client_task_id")
    if not tid:
        await owner_reply_chunks(
            update,
            context,
            "Нет привязанного анализа. Сначала выполни /client … или задачу с ключевыми словами AI Solutions.",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    orch = get_orchestrator()
    await owner_reply_chunks(update, context, "⏳ Генерирую КП (kp_writer)...")
    try:
        result = await _with_telegram_llm(orch.generate_client_kp(int(tid)))
        if result.success:
            context.user_data["last_client_task_id"] = int(tid)
            await split_and_send(
                update,
                f"✅ КП по задаче #{tid}\n\n{result.final_report}",
                context,
                reply_markup=client_analysis_followup_keyboard(int(tid)),
            )
        else:
            await split_and_send(update, f"❌ {result.final_report}", context)
            await send_main_menu(context, update.effective_chat.id)
    except Exception as e:
        logger.error("approve_kp: %s", e, exc_info=True)
        await owner_reply_chunks(update, context, f"❌ {e}")
        await send_main_menu(context, update.effective_chat.id)


async def cmd_brainstorm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    tid = context.user_data.get("last_client_task_id")
    if not tid:
        await owner_reply_chunks(
            update,
            context,
            "Сначала сделай анализ клиента (/client или запрос с ключевыми словами).",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    if not context.args:
        await owner_reply_chunks(
            update,
            context,
            "Использование: /brainstorm твой уточняющий вопрос",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    q = " ".join(context.args).strip()
    orch = get_orchestrator()
    await owner_reply_chunks(update, context, "⏳ Брейншторм (CEO + Architect)...")
    try:
        result = await _with_telegram_llm(orch.run_client_brainstorm(int(tid), q))
        if result.success:
            await split_and_send(
                update,
                f"💬 Добавлено к задаче #{tid}:\n{result.final_report}",
                context,
                reply_markup=client_analysis_followup_keyboard(int(tid)),
            )
        else:
            await split_and_send(update, f"❌ {result.final_report}", context)
            await send_main_menu(context, update.effective_chat.id)
    except Exception as e:
        logger.error("brainstorm: %s", e, exc_info=True)
        await owner_reply_chunks(update, context, f"❌ {e}")
        await send_main_menu(context, update.effective_chat.id)


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    if not context.args:
        await owner_reply_chunks(update, context, "Использование: /task текст задачи")
        await send_main_menu(context, update.effective_chat.id)
        return
    message_text = " ".join(context.args).strip()
    await _run_owner_task(update, context, message_text)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _reply_status_body(update.effective_chat.id, context)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _show_draft_content_list(context, update.effective_chat.id)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return

    await owner_reply_chunks(
        update,
        context,
        "📖 Команды\n\n"
        "/start — меню\n"
        "/report — ежедневный отчёт (аккаунт-менеджер)\n"
        "/clients /students /finance /deadlines — сводки из CRM\n"
        "/agent имя_агента текст — прямой чат (пример: /agent market_analyst тренды)\n"
        "/client описание — анализ клиента (AI Solutions)\n"
        "/approve_kp — КП по последнему анализу\n"
        "/brainstorm вопрос — уточнение по анализу\n"
        "/task текст — запуск задачи\n"
        "/status — статус системы\n"
        "/content — черновики на одобрение\n"
        "/tasks — задачи HQ на сегодня (tasks_v2)\n"
        "/hq_task текст — новая задача в панели\n"
        "/ideas — последние идеи\n"
        "/focus — фокус дня\n"
        "/kpi — ключевые метрики\n"
        "/help — эта справка\n"
        "/cancel — отменить ввод пароля\n\n"
        "Текст с ключевыми словами (клиент, КП, внедрить…) тоже уходит в AI Solutions.",
    )
    await send_main_menu(context, update.effective_chat.id)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _account_manager_telegram_reply(
        update, context,
        "Сформируй ежедневный отчёт строго по шаблону из инструкций (раздел ЕЖЕДНЕВНЫЙ ОТЧЁТ).",
        save_daily=True,
    )


async def cmd_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _account_manager_telegram_reply(update, context, "/clients — статус всех клиентов кратко и по делу.")


async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _account_manager_telegram_reply(update, context, "/students — статус всех учеников.")


async def cmd_finance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _account_manager_telegram_reply(update, context, "/finance — финансовый срез по данным БД.")


async def cmd_deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    await _account_manager_telegram_reply(update, context, "/deadlines — все дедлайны на 2 недели вперёд, таблицей или списком.")


async def cmd_focus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    text = await format_focus_brief_text()
    await split_and_send(update, text, context)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_tasks_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    from datetime import date

    today = date.today().isoformat()
    tasks_all = await list_tasks_v2()
    due = [
        t for t in tasks_all
        if (t.get("execution_date") or t.get("due_date"))
        and str(t.get("execution_date") or t.get("due_date"))[:10] == today
        and (t.get("status") or "") not in ("готово", "отменена")
    ]
    if not due:
        due = [t for t in tasks_all if (t.get("status") or "") not in ("готово", "отменена")][:15]
    lines = ["📋 Задачи (HQ tasks_v2), приоритет на сегодня:\n"]
    for t in due[:20]:
        lines.append(f"• #{t['id']} {t.get('title', '')} [{t.get('status')}]")
    await split_and_send(update, "\n".join(lines), context)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    ideas = (await list_ideas())[:15]
    if not ideas:
        await owner_reply_chunks(update, context, "Идей пока нет.")
        await send_main_menu(context, update.effective_chat.id)
        return
    lines = ["💡 Последние идеи:\n"]
    for i in ideas:
        lines.append(f"• #{i['id']} {i.get('title', '')} ({i.get('status', '')})")
    await split_and_send(update, "\n".join(lines), context)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_kpi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    bm = await get_business_metrics()
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            """SELECT COUNT(*) FROM tasks_v2
               WHERE status NOT IN ('готово', 'отменена')
               AND COALESCE(NULLIF(deadline, ''), NULLIF(due_date, '')) != ''
               AND date(COALESCE(NULLIF(deadline, ''), NULLIF(due_date, ''))) < date('now')"""
        )
        overdue_v2 = int((await cur.fetchone())[0])
    mrr = float(bm.get("total_paid") or 0) / 12.0
    mrr_s = f"{mrr:,.0f} ₽".replace(",", " ")
    msg = (
        "📊 KPI (сводка)\n\n"
        f"Активных клиентов: {bm.get('active_clients', 0)}\n"
        f"Учеников активных: {bm.get('active_students', 0)}\n"
        f"Оплачено всего: {bm.get('total_paid', 0)}\n"
        f"Ожидается: {bm.get('pending_payments', 0)}\n"
        f"MRR (оценка): {mrr_s}\n"
        f"Средний чек: {bm.get('avg_check', 0)}\n"
        f"Просроченных задач HQ: {overdue_v2}\n"
    )
    await split_and_send(update, msg, context)
    await send_main_menu(context, update.effective_chat.id)


async def cmd_hq_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать задачу в панели (tasks_v2), assignee=owner."""
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    if not context.args:
        await owner_reply_chunks(update, context, "Использование: /hq_task Текст задачи")
        await send_main_menu(context, update.effective_chat.id)
        return
    title = " ".join(context.args).strip()
    tid = await insert_task_v2(
        {"title": title, "assignee": "owner", "status": "новая", "priority": "средний"}
    )
    await insert_timeline_event("task", tid, "задача", "Создано из Telegram", created_by="owner")
    await owner_reply_chunks(update, context, f"✅ Задача HQ #{tid} создана. Видна в панели tasks.html")
    await send_main_menu(context, update.effective_chat.id)


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return
    if not context.args or len(context.args) < 2:
        await owner_reply_chunks(
            update, context,
            "Формат: /agent имя_агента ваше сообщение\n"
            "Пример: /agent market_analyst Проанализируй тренды ИИ в ритейле",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    raw_name = context.args[0].strip().lower().replace("-", "_")
    message_text = " ".join(context.args[1:]).strip()
    orch = get_orchestrator()
    agent = orch.team.get(raw_name)
    if not agent:
        await owner_reply_chunks(
            update, context,
            f"Агент «{raw_name}» не найден. Список: /status (agents_count) или панель HQ.",
        )
        await send_main_menu(context, update.effective_chat.id)
        return
    await owner_reply_chunks(update, context, f"⏳ {agent.role} думает…")
    resp = await _with_telegram_llm(
        agent.think(
            message_text,
            context={"source": "telegram", "direct_agent": True},
            task_id=None,
            max_tokens=8000,
            log_execution=False,
        )
    )
    if resp.success:
        await split_and_send(update, resp.text, context)
    else:
        await split_and_send(update, f"❌ {resp.error}", context)
    await send_main_menu(context, update.effective_chat.id)


async def _reply_status_body(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        metrics = await get_metrics()
        orch = get_orchestrator()
        active = len(orch._active_tasks)
        mode = get_default_task_mode()

        body = (
            "🤖 AI AGENCY — СТАТУС\n"
            "──────────────────\n"
            "🟢 Система: онлайн\n"
            f"👥 Агентов: {AGENT_COUNT}\n"
            f"📝 Задач сегодня: {metrics['today_tasks']}\n"
            f"✅ Выполнено: {metrics.get('today_done_tasks', 0)}\n"
            f"💰 Потрачено токенов: {metrics['today_tokens']:,} (сегодня) / "
            f"{metrics['total_tokens']:,} (всего)\n"
            f"🔄 Активных задач сейчас: {active}\n"
            "──────────────────\n"
            f"Режим задач: {mode}\n"
            f"Автопостинг: {'ВКЛ' if is_auto_publish_on() else 'ВЫКЛ'}"
        )
        await send_messages_cleaned(context, chat_id, body)
    except Exception as e:
        await send_messages_cleaned(context, chat_id, f"❌ Ошибка статуса: {e}")


async def _show_draft_content_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        drafts = await get_content(status="draft", limit=15)
        if not drafts:
            await send_messages_cleaned(context, chat_id, "✏️ Нет контента в статусе draft.")
            return

        lines = ["✏️ Контент на одобрение (draft)\n"]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for row in drafts[:10]:
            cid = row["id"]
            topic = (row.get("topic") or "")[:50]
            ch = row.get("channel") or ""
            lines.append(f"#{cid} · {ch} · {topic}")
            keyboard_rows.append(content_item_keyboard(cid))

        await send_messages_cleaned(
            context,
            chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )
    except Exception as e:
        await send_messages_cleaned(context, chat_id, f"❌ Ошибка: {e}")


async def _show_task_history(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        tasks = await get_tasks(limit=5)
        if not tasks:
            await send_messages_cleaned(context, chat_id, "📋 Задач пока нет.")
            return

        lines = ["📋 Последние задачи\n"]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for t in tasks:
            tid = t["id"]
            st = t["status"]
            msg = (t.get("owner_message") or "")[:40].replace("\n", " ")
            lines.append(f"#{tid} | {st} | {msg}")
            keyboard_rows.append(
                [InlineKeyboardButton(f"📄 Детали #{tid}", callback_data=f"td_{tid}")]
            )
        await send_messages_cleaned(
            context,
            chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )
    except Exception as e:
        await send_messages_cleaned(context, chat_id, f"❌ Ошибка: {e}")


# ── Задачи ──


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await owner_reply_chunks(update, context, "⛔ Бот не доступен.")
        return

    if context.user_data.get("awaiting_admin_password"):
        await _handle_admin_password_message(update, context)
        return

    message_text = (update.message.text or "").strip()
    if not message_text:
        return

    await _run_owner_task(update, context, message_text)


async def _run_client_analysis_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_text: str,
):
    orch = get_orchestrator()
    mode = get_default_task_mode()
    await owner_reply_chunks(
        update,
        context,
        f"⏳ AI Solutions: анализ клиента (режим {mode})...",
    )
    try:
        result = await _with_telegram_llm(orch.run_client_analysis(message_text, task_mode=mode))
        if result.success:
            context.user_data["last_client_task_id"] = result.task_id
            reply_text = (
                f"✅ AI Solutions · задача #{result.task_id}\n"
                f"⏱ {result.duration_seconds:.1f}с · шагов: {len(result.chain)}\n\n"
                f"{result.final_report}"
            )
            await split_and_send(
                update,
                reply_text,
                context,
                reply_markup=client_analysis_followup_keyboard(result.task_id),
            )
        else:
            await split_and_send(
                update,
                f"❌ Задача #{result.task_id}: {result.final_report}",
                context,
            )
            await send_main_menu(context, update.effective_chat.id)
    except Exception as e:
        logger.error("client analysis: %s", e, exc_info=True)
        await owner_reply_chunks(update, context, f"❌ {e}")
        await send_main_menu(context, update.effective_chat.id)


async def _handle_admin_password_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = (update.message.text or "").strip()
    context.user_data.pop("awaiting_admin_password", None)
    if pw.lower() in ("/cancel", "отмена"):
        await owner_reply_chunks(update, context, "Смена пароля отменена.")
        await send_main_menu(context, update.effective_chat.id)
        return
    if len(pw) < 4:
        await owner_reply_chunks(
            update,
            context,
            "Пароль слишком короткий. Попробуй ещё раз или /cancel",
        )
        context.user_data["awaiting_admin_password"] = True
        return
    try:
        update_env_file("ADMIN_PASSWORD", pw)
        await owner_reply_chunks(
            update,
            context,
            "✅ Пароль панели обновлён в .env (перезапусти main.py при необходимости).",
        )
    except Exception as e:
        await owner_reply_chunks(update, context, f"❌ Не удалось записать .env: {e}")
    await send_main_menu(context, update.effective_chat.id)


async def _run_owner_task(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
    orch = get_orchestrator()
    mode = get_default_task_mode()

    await owner_reply_chunks(
        update,
        context,
        f"⏳ Задача запущена (режим {mode}). Подожди 1–3 мин…",
    )

    try:
        result = await _with_telegram_llm(orch.run_task(message_text, task_mode=mode))

        if result.success:
            reply_text = (
                f"✅ Задача #{result.task_id} выполнена\n"
                f"⏱ {result.duration_seconds:.1f}с · агентов в цепочке: {len(result.chain)}\n\n"
                f"{result.final_report}"
            )
            ai_sol = any(step.agent_name == "client_ceo" for step in result.chain)
            if ai_sol:
                context.user_data["last_client_task_id"] = result.task_id
                kb = client_analysis_followup_keyboard(result.task_id)
            else:
                kb = post_task_keyboard(result.task_id)
            await split_and_send(
                update,
                reply_text,
                context,
                reply_markup=kb,
            )
        else:
            await split_and_send(
                update,
                f"❌ Задача #{result.task_id} — ошибка:\n\n{result.final_report}",
                context,
            )
            await send_main_menu(context, update.effective_chat.id)

    except Exception as e:
        logger.error("Ошибка выполнения задачи: %s", e, exc_info=True)
        await owner_reply_chunks(update, context, f"❌ Ошибка: {e}")
        await send_main_menu(context, update.effective_chat.id)


# ── Callbacks ──


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    if not is_owner(update):
        await query.answer("⛔ Не доступно", show_alert=True)
        return

    data = query.data or ""
    chat_id = query.message.chat_id if query.message else query.from_user.id

    try:
        if data == "m_main":
            await query.answer()
            await send_main_menu(context, chat_id)

        elif data == "m_new":
            await query.answer()
            await send_messages_cleaned(
                context,
                chat_id,
                "🚀 Опиши задачу одним сообщением — сразу запущу команду.",
            )
            await send_main_menu(context, chat_id)

        elif data == "am_report":
            await query.answer()
            orch = get_orchestrator()
            await send_messages_cleaned(context, chat_id, "⏳ Аккаунт-менеджер: ежедневный отчёт…")
            snap = await build_account_snapshot_json()
            user_msg = (
                "Сформируй ежедневный отчёт строго по шаблону из инструкций.\n\nДАННЫЕ ИЗ БД:\n" + snap
            )
            resp = await _with_telegram_llm(
                orch.team.account_manager.think(
                    user_msg, context={"source": "telegram_cb"}, task_id=None, max_tokens=8000, log_execution=False,
                )
            )
            if resp.success:
                payload = json.dumps({"text": resp.text, "generated_at": datetime.utcnow().isoformat()}, ensure_ascii=False)
                await save_daily_report(date.today().isoformat(), payload)
                await split_and_send(chat_id, resp.text, context)
            else:
                await send_messages_cleaned(context, chat_id, f"❌ {resp.error}")
            await send_main_menu(context, chat_id)

        elif data == "am_clients":
            await query.answer()
            orch = get_orchestrator()
            await send_messages_cleaned(context, chat_id, "⏳ Клиенты…")
            snap = await build_account_snapshot_json()
            resp = await _with_telegram_llm(
                orch.team.account_manager.think(
                    "/clients — статус всех клиентов.\n\nДАННЫЕ ИЗ БД:\n" + snap,
                    task_id=None, max_tokens=8000, log_execution=False,
                )
            )
            await split_and_send(chat_id, resp.text if resp.success else f"❌ {resp.error}", context)
            await send_main_menu(context, chat_id)

        elif data == "am_students":
            await query.answer()
            orch = get_orchestrator()
            await send_messages_cleaned(context, chat_id, "⏳ Ученики…")
            snap = await build_account_snapshot_json()
            resp = await _with_telegram_llm(
                orch.team.account_manager.think(
                    "/students — статус учеников.\n\nДАННЫЕ ИЗ БД:\n" + snap,
                    task_id=None, max_tokens=8000, log_execution=False,
                )
            )
            await split_and_send(chat_id, resp.text if resp.success else f"❌ {resp.error}", context)
            await send_main_menu(context, chat_id)

        elif data == "am_finance":
            await query.answer()
            orch = get_orchestrator()
            await send_messages_cleaned(context, chat_id, "⏳ Финансы…")
            snap = await build_account_snapshot_json()
            resp = await _with_telegram_llm(
                orch.team.account_manager.think(
                    "/finance — финансовый срез.\n\nДАННЫЕ ИЗ БД:\n" + snap,
                    task_id=None, max_tokens=8000, log_execution=False,
                )
            )
            await split_and_send(chat_id, resp.text if resp.success else f"❌ {resp.error}", context)
            await send_main_menu(context, chat_id)

        elif data == "am_deadlines":
            await query.answer()
            orch = get_orchestrator()
            await send_messages_cleaned(context, chat_id, "⏳ Дедлайны…")
            snap = await build_account_snapshot_json()
            resp = await _with_telegram_llm(
                orch.team.account_manager.think(
                    "/deadlines — на 2 недели вперёд.\n\nДАННЫЕ ИЗ БД:\n" + snap,
                    task_id=None, max_tokens=8000, log_execution=False,
                )
            )
            await split_and_send(chat_id, resp.text if resp.success else f"❌ {resp.error}", context)
            await send_main_menu(context, chat_id)

        elif data == "m_status":
            await query.answer()
            await _reply_status_body(chat_id, context)
            await send_main_menu(context, chat_id)

        elif data == "m_hist":
            await query.answer()
            await _show_task_history(context, chat_id)
            await send_main_menu(context, chat_id)

        elif data == "m_cont":
            await query.answer()
            await _show_draft_content_list(context, chat_id)
            await send_main_menu(context, chat_id)

        elif data == "m_set":
            await query.answer()
            await send_messages_cleaned(
                context,
                chat_id,
                "⚙️ Настройки",
                reply_markup=settings_keyboard(),
            )
            await send_main_menu(context, chat_id)

        elif data == "set_mode":
            nxt = cycle_task_mode()
            await query.answer(f"Режим: {nxt}")
            try:
                await query.edit_message_reply_markup(reply_markup=settings_keyboard())
            except Exception:
                await send_messages_cleaned(
                    context,
                    chat_id,
                    f"🔋 Режим задач: {nxt} (сохранено в .env)",
                )
            await send_main_menu(context, chat_id)

        elif data == "set_pub":
            on = toggle_auto_publish()
            await query.answer("Автопостинг переключён")
            try:
                await query.edit_message_reply_markup(reply_markup=settings_keyboard())
            except Exception:
                pass
            await send_messages_cleaned(
                context,
                chat_id,
                f"📢 Автопостинг: {'ВКЛ' if on else 'ВЫКЛ'}",
            )
            await send_main_menu(context, chat_id)

        elif data == "set_pw":
            await query.answer()
            context.user_data["awaiting_admin_password"] = True
            await send_messages_cleaned(
                context,
                chat_id,
                "🔑 Отправь новый пароль одним сообщением.\n/cancel — отмена.",
            )
            await send_main_menu(context, chat_id)

        elif data == "set_about":
            await query.answer()
            await send_messages_cleaned(
                context,
                chat_id,
                (
                    "ℹ️ AI Agency Bot\n\n"
                    f"Агентов в команде: {AGENT_COUNT}\n"
                    f"Режим по умолчанию: {get_default_task_mode()}\n"
                    "Панель API и .env на сервере.\n"
                    "Документация: см. README проекта."
                ),
            )
            await send_main_menu(context, chat_id)

        elif data.startswith("chain_"):
            await query.answer()
            task_id = int(data.split("_", 1)[1])
            await _show_chain(chat_id, task_id, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("td_"):
            await query.answer()
            task_id = int(data.split("_", 1)[1])
            await _show_task_detail(chat_id, task_id, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("tredo_"):
            await query.answer("Переделываю…")
            task_id = int(data.split("_", 1)[1])
            await _redo_task(chat_id, task_id, context)

        elif data.startswith("tok_"):
            await query.answer("Принято!")
            await send_messages_cleaned(context, chat_id, "✅ Отчёт принят. Спасибо!")
            await send_main_menu(context, chat_id)

        elif data.startswith("tsv_"):
            await query.answer()
            task_id = int(data.split("_", 1)[1])
            await _save_task_report(chat_id, task_id, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("tpub_"):
            await query.answer()
            task_id = int(data.split("_", 1)[1])
            await _publish_task_content(chat_id, task_id, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("cv_"):
            await query.answer()
            cid = int(data.split("_", 1)[1])
            await _content_view(chat_id, cid, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("ca_"):
            await query.answer("Одобрено")
            cid = int(data.split("_", 1)[1])
            await update_content_status(cid, "approved")
            await send_messages_cleaned(context, chat_id, f"✅ Контент #{cid} одобрен.")
            await send_main_menu(context, chat_id)

        elif data.startswith("cr_"):
            await query.answer("Отклонено")
            cid = int(data.split("_", 1)[1])
            await update_content_status(cid, "rejected", qa_notes="Отклонено из Telegram")
            await send_messages_cleaned(context, chat_id, f"❌ Контент #{cid} отклонён.")
            await send_main_menu(context, chat_id)

        elif data.startswith("publish_"):
            await query.answer()
            content_id = int(data.split("_", 1)[1])
            await _publish_content_by_id(chat_id, content_id, context)
            await send_main_menu(context, chat_id)

        elif data.startswith("ckp_"):
            await query.answer()
            tid = int(data.split("_", 1)[1])
            context.user_data["last_client_task_id"] = tid
            await send_messages_cleaned(context, chat_id, "⏳ Генерирую КП...")
            res = await _with_telegram_llm(get_orchestrator().generate_client_kp(tid))
            if res.success:
                await split_and_send(
                    chat_id,
                    f"✅ КП · задача #{tid}\n\n{res.final_report}",
                    context,
                    reply_markup=client_analysis_followup_keyboard(tid),
                )
            else:
                await split_and_send(chat_id, f"❌ {res.final_report}", context)
                await send_main_menu(context, chat_id)

        elif data.startswith("cbs_"):
            tid = int(data.split("_", 1)[1])
            context.user_data["last_client_task_id"] = tid
            await query.answer(
                "Введи команду /brainstorm и вопрос в том же сообщении",
                show_alert=True,
            )
            await send_main_menu(context, chat_id)

        elif data.startswith("credo_"):
            await query.answer("Новый прогон...")
            tid = int(data.split("_", 1)[1])
            await _client_redo_analysis(chat_id, tid, context)

        elif data == "cnewc":
            await query.answer()
            await send_messages_cleaned(
                context,
                chat_id,
                "Новый клиент: /client описание ситуации или обычное сообщение с контекстом клиента.",
            )
            await send_main_menu(context, chat_id)

        else:
            await query.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        logger.error("Callback error: %s", e, exc_info=True)
        await query.answer("Ошибка", show_alert=True)
        await send_messages_cleaned(context, chat_id, f"❌ {e}")
        await send_main_menu(context, chat_id)


async def _client_redo_analysis(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Новая задача с тем же описанием — полный пайплайн AI Solutions."""
    try:
        old = await get_task(task_id)
        if not old:
            await send_messages_cleaned(context, chat_id, "Задача не найдена.")
            await send_main_menu(context, chat_id)
            return
        msg = old.get("owner_message") or ""
        if msg.startswith("[AI Solutions повтор]"):
            msg = msg.replace("[AI Solutions повтор] ", "", 1).strip()
        nid = await create_task(f"[AI Solutions повтор] {msg[:2000]}")
        orch = get_orchestrator()
        mode = get_default_task_mode()
        await send_messages_cleaned(
            context,
            chat_id,
            f"⏳ Пересмотр: новая задача #{nid} (режим {mode})...",
        )
        result = await _with_telegram_llm(orch.run_client_analysis(msg, task_id=nid, task_mode=mode))
        if result.success:
            context.user_data["last_client_task_id"] = result.task_id
            await split_and_send(
                chat_id,
                f"✅ Задача #{result.task_id}\n⏱ {result.duration_seconds:.1f}с\n\n{result.final_report}",
                context,
                reply_markup=client_analysis_followup_keyboard(result.task_id),
            )
        else:
            await split_and_send(chat_id, f"❌ {result.final_report}", context)
            await send_main_menu(context, chat_id)
    except Exception as e:
        logger.error("client redo: %s", e, exc_info=True)
        await send_messages_cleaned(context, chat_id, f"❌ {e}")
        await send_main_menu(context, chat_id)


async def _show_chain(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        chain = await get_task_chain(task_id)
        if not chain:
            await send_messages_cleaned(context, chat_id, "Цепочка пуста.")
            return

        text = f"📋 Цепочка задачи #{task_id}\n\n"
        for i, step in enumerate(chain, 1):
            status_icon = "✅" if step["status"] == "done" else "❌"
            text += (
                f"{i}. {status_icon} {step['agent_name']} ({step['agent_role']})\n"
                f"   Токены: {step['tokens_used']}\n"
                f"   Вход: {(step['input_brief'] or '')[:120]}…\n\n"
            )
        await split_and_send(chat_id, text, context)
    except Exception as e:
        await send_messages_cleaned(context, chat_id, f"❌ {e}")


async def _show_task_detail(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    task = await get_task(task_id)
    if not task:
        await send_messages_cleaned(context, chat_id, "Задача не найдена.")
        return
    res = task.get("result") or "—"
    msg = task.get("owner_message") or "—"
    body = (
        f"📄 Задача #{task_id}\n"
        f"Статус: {task.get('status')}\n\n"
        f"Запрос:\n{msg}\n\n"
        f"Отчёт / результат:\n{res}"
    )
    await split_and_send(chat_id, body, context)


async def _save_task_report(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    task = await get_task(task_id)
    if not task:
        await send_messages_cleaned(context, chat_id, "Задача не найдена.")
        return
    msg = task.get("owner_message") or ""
    res = task.get("result") or ""
    plain = (
        f"Задача #{task_id}\n"
        f"Статус: {task.get('status')}\n"
        f"Создана: {task.get('created_at')}\n\n"
        f"--- Запрос ---\n{msg}\n\n"
        f"--- Отчёт ---\n{res}\n"
    )
    buf = BytesIO(plain.encode("utf-8"))
    await context.bot.send_document(
        chat_id=chat_id,
        document=InputFile(buf, filename=f"task_{task_id}_report.txt"),
        caption=f"💾 Отчёт задачи #{task_id}",
    )


async def _publish_task_content(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_content_for_task(task_id)
    cand = None
    for r in rows:
        if r.get("channel") == "telegram" and r.get("status") in ("draft", "approved"):
            cand = r
            break
    if cand is None:
        for r in rows:
            if r.get("status") in ("draft", "approved"):
                cand = r
                break
    if cand is None:
        await send_messages_cleaned(
            context,
            chat_id,
            "Нет черновика/одобренного контента для публикации по этой задаче.",
        )
        return
    await _publish_content_by_id(chat_id, cand["id"], context)


async def _publish_content_by_id(chat_id: int, content_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        content = await get_content_by_id(content_id)
        if not content:
            await send_messages_cleaned(context, chat_id, "Контент не найден.")
            return

        channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
        if not channel_id:
            await update_content_status(content_id, "approved")
            await send_messages_cleaned(
                context,
                chat_id,
                "⚠️ TELEGRAM_CHANNEL_ID пуст — контент одобрен, в канал не отправлен.",
            )
            return

        body = content["body"] or ""
        await send_messages_cleaned(context, channel_id, body)
        await update_content_status(content_id, "published")
        await send_messages_cleaned(
            context,
            chat_id,
            f"✅ Контент #{content_id} опубликован в канал.",
        )
    except Exception as e:
        logger.error("Публикация: %s", e, exc_info=True)
        await send_messages_cleaned(context, chat_id, f"❌ Ошибка публикации: {e}")


async def _content_view(chat_id: int, content_id: int, context: ContextTypes.DEFAULT_TYPE):
    content = await get_content_by_id(content_id)
    if not content:
        await send_messages_cleaned(context, chat_id, "Контент не найден.")
        return
    header = f"👁 #{content_id} · {content.get('channel')} · {content.get('topic')}\n\n"
    await split_and_send(chat_id, header + (content.get("body") or ""), context)


async def _redo_task(chat_id: int, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        task = await get_task(task_id)
        if not task:
            await send_messages_cleaned(context, chat_id, "Задача не найдена.")
            await send_main_menu(context, chat_id)
            return

        original_message = task["owner_message"]
        orch = get_orchestrator()
        mode = get_default_task_mode()

        await send_messages_cleaned(
            context,
            chat_id,
            f"🔄 Переделываю #{task_id} (режим {mode})…",
        )

        result = await _with_telegram_llm(
            orch.run_task(
                f"[ПЕРЕДЕЛАТЬ] {original_message}\n\nПопробуй другой подход, улучши качество.",
                task_mode=mode,
            )
        )

        if result.success:
            reply_text = (
                f"✅ Переделано → задача #{result.task_id}\n"
                f"⏱ {result.duration_seconds:.1f}с\n\n"
                f"{result.final_report}"
            )
            await split_and_send(
                chat_id,
                reply_text,
                context,
                reply_markup=post_task_keyboard(result.task_id),
            )
        else:
            await split_and_send(
                chat_id,
                f"❌ Ошибка: {result.final_report}",
                context,
            )
            await send_main_menu(context, chat_id)
    except Exception as e:
        logger.error("Redo: %s", e, exc_info=True)
        await send_messages_cleaned(context, chat_id, f"❌ {e}")
        await send_main_menu(context, chat_id)


# ── Создание и запуск бота ──


def create_bot_application() -> Application:
    """Создать экземпляр бота (без запуска)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token or token == "ЗАМЕНИ_НА_ТОКЕН_БОТА":
        logger.warning("TELEGRAM_BOT_TOKEN не задан — бот не будет работать")
        return None

    app_builder = Application.builder().token(token).build()

    app_builder.add_handler(CommandHandler("start", cmd_start))
    app_builder.add_handler(CommandHandler("client", cmd_client))
    app_builder.add_handler(CommandHandler("approve_kp", cmd_approve_kp))
    app_builder.add_handler(CommandHandler("brainstorm", cmd_brainstorm))
    app_builder.add_handler(CommandHandler("task", cmd_task))
    app_builder.add_handler(CommandHandler("cancel", cmd_cancel))
    app_builder.add_handler(CommandHandler("status", cmd_status))
    app_builder.add_handler(CommandHandler("content", cmd_content))
    app_builder.add_handler(CommandHandler("help", cmd_help))
    app_builder.add_handler(CommandHandler("report", cmd_report))
    app_builder.add_handler(CommandHandler("clients", cmd_clients))
    app_builder.add_handler(CommandHandler("students", cmd_students))
    app_builder.add_handler(CommandHandler("finance", cmd_finance))
    app_builder.add_handler(CommandHandler("deadlines", cmd_deadlines))
    app_builder.add_handler(CommandHandler("tasks", cmd_tasks_v2))
    app_builder.add_handler(CommandHandler("hq_task", cmd_hq_task))
    app_builder.add_handler(CommandHandler("ideas", cmd_ideas))
    app_builder.add_handler(CommandHandler("focus", cmd_focus))
    app_builder.add_handler(CommandHandler("kpi", cmd_kpi))
    app_builder.add_handler(CommandHandler("agent", cmd_agent))
    app_builder.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_builder.add_handler(CallbackQueryHandler(handle_callback))

    return app_builder


async def run_bot(orch: Orchestrator):
    """Запустить бота в режиме polling."""
    set_orchestrator(orch)
    bot_app = create_bot_application()
    if bot_app is None:
        logger.warning("Telegram бот не запущен — токен не задан")
        while True:
            await asyncio.sleep(3600)
        return

    logger.info("Telegram бот запускается...")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram бот запущен. Ожидаю сообщений от владельца (ID: %s)", get_owner_id())

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Telegram бот останавливается...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
