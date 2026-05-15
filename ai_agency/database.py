"""
Модуль работы с SQLite через aiosqlite.
Все операции асинхронные. БД хранится в файле agency.db.
"""

import asyncio
import aiosqlite
import json
import logging
import os
import shutil
from datetime import datetime, date, timedelta
from pathlib import Path

logger = logging.getLogger("database")

from delivery_template_seed import FULL_DELIVERY_TEMPLATES

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "agency.db")))

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(Path(__file__).parent / "backups")))


async def backup_db(tag: str = "") -> Path:
    """Создать резервную копию БД. Возвращает путь к файлу бэкапа."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    backup_name = f"agency_{ts}{suffix}.db"
    dst = BACKUP_DIR / backup_name
    shutil.copy2(str(DB_PATH), str(dst))
    logger.info("Бэкап БД создан: %s", dst)
    # Удаляем старые бэкапы (оставляем последние 10)
    backups = sorted(BACKUP_DIR.glob("agency_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[10:]:
        old.unlink(missing_ok=True)
    return dst

_app_settings_schema_ok = False


async def ensure_app_settings_table() -> None:
    """Для БД, созданных до появления app_settings — создать таблицу без полного пересоздания."""
    global _app_settings_schema_ok
    if _app_settings_schema_ok:
        return
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
    _app_settings_schema_ok = True


async def _get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Создать все таблицы если не существуют."""
    # Бэкап БД перед миграциями (если файл уже существует)
    if DB_PATH.exists():
        try:
            await backup_db("startup")
        except Exception as e:
            logger.warning("Не удалось создать бэкап при старте: %s", e)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                owner_message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','done','error')),
                assigned_to TEXT NOT NULL DEFAULT 'chief_of_staff',
                result TEXT,
                error TEXT,
                duration_seconds REAL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                agent_name TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                input_brief TEXT NOT NULL,
                output_text TEXT,
                status TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running','done','error')),
                tokens_used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                parent_agent TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tasks(id),
                channel TEXT NOT NULL,
                topic TEXT NOT NULL,
                body TEXT NOT NULL,
                rubric TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft','approved','published','rejected')),
                qa_passed INTEGER DEFAULT 0,
                qa_notes TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                sent_to_telegram INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS backlog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open','in_progress','done','cancelled')),
                assigned_agent TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                done_at TEXT
            )
        """)

        # ── HQ: Клиенты ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT,
                contact TEXT,
                service_type TEXT DEFAULT 'бот'
                    CHECK(service_type IN ('бот','автоматизация','аналитика','сайт','аудит','комплекс','другое')),
                status TEXT NOT NULL DEFAULT 'lead'
                    CHECK(status IN ('lead','active','paused','done','cancelled')),
                start_date TEXT,
                end_date TEXT,
                total_amount REAL DEFAULT 0,
                paid_amount REAL DEFAULT 0,
                next_action TEXT,
                next_action_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Проекты ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'discovery'
                    CHECK(stage IN ('discovery','design','development','testing','launch','support')),
                progress INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                deadline TEXT,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Задачи по проектам ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK(status IN ('todo','in_progress','done')),
                due_date TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Ученики ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact TEXT,
                program TEXT,
                start_date TEXT,
                total_sessions INTEGER DEFAULT 0,
                completed_sessions INTEGER DEFAULT 0,
                payment_total REAL DEFAULT 0,
                payment_received REAL DEFAULT 0,
                next_session_date TEXT,
                progress_notes TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','paused','done')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Задания ученикам ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS student_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                assigned_date TEXT NOT NULL DEFAULT (date('now')),
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'assigned'
                    CHECK(status IN ('assigned','submitted','reviewed','done')),
                feedback TEXT,
                grade INTEGER CHECK(grade IS NULL OR (grade >= 1 AND grade <= 10)),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Напоминания ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL DEFAULT 'custom'
                    CHECK(type IN ('client','student','custom')),
                related_id INTEGER,
                text TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Ежедневные отчёты ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── HQ: Кэш метрик ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS metrics_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                value TEXT,
                date TEXT NOT NULL DEFAULT (date('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS hq_agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_executions_task ON agent_executions(task_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_content_status ON content(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_students_status ON students(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_hq_agent_messages ON hq_agent_messages(agent_name, created_at)
        """)

        # ── HQ: Личные заметки владельца ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS owner_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'note'
                    CHECK(status IN ('note','queued','done')),
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK(priority IN ('low','normal','high')),
                sent_to_team INTEGER NOT NULL DEFAULT 0,
                task_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_owner_notes_created ON owner_notes(created_at)
        """)

        # ── HQ: посты в Telegram-канал (автопостинг) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channel_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                rubric TEXT,
                text TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft','approved','published','rejected')),
                telegram_message_id INTEGER,
                published_at TEXT,
                qa_score INTEGER,
                qa_notes TEXT,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_channel_posts_status ON channel_posts(status, created_at)
        """)

        # ── HQ users (роли: owner / pm / executor / reviewer) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hq_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                login TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'executor',
                telegram TEXT DEFAULT '',
                email TEXT DEFAULT '',
                github_username TEXT DEFAULT '',
                specialization TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hq_users_login ON hq_users(login)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hq_users_role ON hq_users(role)")

        # ── HQ sessions (T-1-011: persistent sessions across restarts) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hq_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES hq_users(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hq_sessions_token ON hq_sessions(token)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hq_sessions_expires ON hq_sessions(expires_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hq_sessions_user ON hq_sessions(user_id)")

        # ── Исполнители (могут быть привязаны к hq_users.id) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS executors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'executor',
                telegram TEXT DEFAULT '',
                email TEXT DEFAULT '',
                github_username TEXT DEFAULT '',
                specialization TEXT DEFAULT '',
                status TEXT DEFAULT 'Доступен',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES hq_users(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_executors_user ON executors(user_id)")

        # ── Delivery проекты (отдельный bounded context от CRM projects) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client_id INTEGER DEFAULT NULL,
                crm_project_id INTEGER DEFAULT NULL,
                description TEXT DEFAULT '',
                type TEXT DEFAULT 'Другое',
                status TEXT DEFAULT 'Подготовка',
                owner_id INTEGER DEFAULT 1,
                github_repo_url TEXT DEFAULT '',
                vercel_project_url TEXT DEFAULT '',
                production_url TEXT DEFAULT '',
                start_date TEXT DEFAULT '',
                deadline TEXT DEFAULT '',
                budget REAL DEFAULT 0,
                priority TEXT DEFAULT 'Medium',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
                FOREIGN KEY (owner_id) REFERENCES hq_users(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_projects_client ON delivery_projects(client_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_projects_status ON delivery_projects(status)")

        # ── delivery_project_members УБРАНО (P2-2): связь команды на проекте
        #    идёт через delivery_tasks.assignee_id; отдельная таблица не нужна.
        # ── Этапы проекта ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'Не начат',
                stage_order INTEGER DEFAULT 0,
                start_date TEXT DEFAULT '',
                deadline TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES delivery_projects(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_stages_project ON delivery_stages(project_id, stage_order)")

        # ── Задачи производства ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                stage_id INTEGER DEFAULT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                goal TEXT DEFAULT '',
                assignee_id INTEGER DEFAULT NULL,
                reviewer_id INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'Backlog',
                priority TEXT DEFAULT 'Medium',
                branch_name TEXT DEFAULT '',
                pull_request_url TEXT DEFAULT '',
                preview_url TEXT DEFAULT '',
                production_url TEXT DEFAULT '',
                deadline TEXT DEFAULT '',
                result_comment TEXT DEFAULT '',
                review_comment TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES delivery_projects(id) ON DELETE CASCADE,
                FOREIGN KEY (stage_id) REFERENCES delivery_stages(id) ON DELETE SET NULL,
                FOREIGN KEY (assignee_id) REFERENCES executors(id) ON DELETE SET NULL,
                FOREIGN KEY (reviewer_id) REFERENCES executors(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_tasks_project ON delivery_tasks(project_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_tasks_stage ON delivery_tasks(stage_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_tasks_assignee ON delivery_tasks(assignee_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_tasks_status ON delivery_tasks(status)")

        # ── Чеклист задачи ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_checklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                is_completed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES delivery_tasks(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_checklist_task ON delivery_checklist(task_id)")

        # ── Комментарии задачи ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER DEFAULT NULL,
                author_name TEXT DEFAULT '',
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES delivery_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES hq_users(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_comments_task ON delivery_comments(task_id)")

        # ── Шаблоны проектов ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                stages_json TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                icon TEXT DEFAULT '📋',
                estimated_days INTEGER DEFAULT 14,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()
        logger.info("База данных инициализирована: %s", DB_PATH)

    await _migrate_clients_service_type_drugoe()
    await _migrate_v3()
    await _migrate_remove_check_constraints()
    await _migrate_fix_project_tasks_fk()
    await _migrate_fix_projects_fk()
    await _migrate_fix_payments_fk()
    await _migrate_drop_legacy_tables()
    await _migrate_drop_delivery_project_members()
    await _migrate_executors_level()
    await _migrate_delivery_templates_expand()
    await _seed_owner_user()
    await _seed_delivery_templates()


async def _migrate_delivery_templates_expand() -> None:
    """Добавить description, icon, estimated_days к delivery_templates."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await _add_column_if_missing(db, "delivery_templates", "description", "TEXT DEFAULT ''")
        await _add_column_if_missing(db, "delivery_templates", "icon", "TEXT DEFAULT '📋'")
        await _add_column_if_missing(db, "delivery_templates", "estimated_days", "INTEGER DEFAULT 14")
        await db.commit()
    logger.info("Migration: delivery_templates расширена (description, icon, estimated_days)")


async def _migrate_drop_delivery_project_members() -> None:
    """Удалить мёртвую таблицу delivery_project_members (P2-2).

    Связи команды на проекте управляются через delivery_tasks.assignee_id —
    отдельная many-to-many не нужна. Идемпотентно.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='delivery_project_members'"
        )
        row = await cur.fetchone()
        if not row:
            return
        await db.execute("DROP TABLE IF EXISTS delivery_project_members")
        await db.commit()
        logger.info("Миграция: удалена неиспользуемая таблица delivery_project_members")


async def _migrate_executors_level() -> None:
    """Колонка level в executors (junior / middle / senior)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executors'"
        )
        if not await cur.fetchone():
            return
        await _add_column_if_missing(db, "executors", "level", "TEXT DEFAULT 'middle'")
        await db.commit()
    logger.info("Migration: executors.level added")


async def _migrate_clients_service_type_drugoe() -> None:
    """Расширить CHECK service_type: добавить «другое» (старые БД без пересоздания файла)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='clients'"
        )
        row = await cur.fetchone()
        if not row or not row[0] or "другое" in row[0]:
            return
        # Если CHECK уже снят (миграцией _migrate_remove_check_constraints) — пропускаем.
        if "CHECK" not in row[0]:
            return
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute("ALTER TABLE clients RENAME TO clients_old")
        await db.execute("""
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT,
                contact TEXT,
                service_type TEXT DEFAULT 'бот'
                    CHECK(service_type IN ('бот','автоматизация','аналитика','сайт','аудит','комплекс','другое')),
                status TEXT NOT NULL DEFAULT 'lead'
                    CHECK(status IN ('lead','active','paused','done','cancelled')),
                start_date TEXT,
                end_date TEXT,
                total_amount REAL DEFAULT 0,
                paid_amount REAL DEFAULT 0,
                next_action TEXT,
                next_action_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "INSERT INTO clients SELECT * FROM clients_old"
        )
        await db.execute("DROP TABLE clients_old")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)"
        )
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        logger.info("Миграция clients: добавлено значение service_type «другое»")


async def _migrate_remove_check_constraints() -> None:
    """Убрать CHECK constraints с clients.service_type и clients.status для свободного ввода."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='clients'"
        )
        row = await cur.fetchone()
        if not row or not row[0]:
            return
        ddl = row[0]
        if "CHECK" not in ddl:
            return
        logger.info("Миграция: убираем CHECK constraints из clients...")
        # Получаем все текущие колонки (после _migrate_v3)
        cols_info = await db.execute_fetchall("PRAGMA table_info(clients)")
        col_names = [c[1] for c in cols_info]
        cols_csv = ", ".join(col_names)
        # Убираем CHECK(...) из DDL — учитываем вложенные скобки (IN(...))
        def _strip_check(src: str) -> str:
            out = []
            i = 0
            n = len(src)
            while i < n:
                # Ищем слово CHECK с учётом границ
                if src[i:i+5].upper() == "CHECK" and (i == 0 or not src[i-1].isalnum()):
                    j = i + 5
                    # пропускаем пробелы
                    while j < n and src[j] in " \t\r\n":
                        j += 1
                    if j < n and src[j] == "(":
                        depth = 1
                        j += 1
                        while j < n and depth > 0:
                            if src[j] == "(":
                                depth += 1
                            elif src[j] == ")":
                                depth -= 1
                            j += 1
                        # Сдираем возможные пробелы перед CHECK
                        while out and out[-1] in " \t\r\n":
                            out.pop()
                        i = j
                        continue
                out.append(src[i])
                i += 1
            return "".join(out)
        new_ddl = _strip_check(ddl)
        new_ddl = new_ddl.replace("CREATE TABLE clients", "CREATE TABLE clients_nocheck", 1)
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute(new_ddl)
        await db.execute(f"INSERT INTO clients_nocheck ({cols_csv}) SELECT {cols_csv} FROM clients")
        await db.execute("DROP TABLE clients")
        await db.execute("ALTER TABLE clients_nocheck RENAME TO clients")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        logger.info("Миграция: CHECK constraints убраны из clients")


async def _migrate_fix_project_tasks_fk() -> None:
    """Починить FK у project_tasks: ссылка на projects_old → projects (после битой старой миграции)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_tasks'"
        )
        row = await cur.fetchone()
        if not row or not row[0]:
            return
        if "projects_old" not in row[0]:
            return
        logger.info("Миграция: чиним FK в project_tasks (projects_old → projects)...")
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute("PRAGMA legacy_alter_table=ON")
        # Берём реальные колонки старой таблицы
        cur = await db.execute("PRAGMA table_info(project_tasks)")
        old_cols = [r[1] for r in await cur.fetchall()]
        cols_csv = ", ".join(old_cols)
        await db.execute("ALTER TABLE project_tasks RENAME TO project_tasks_broken")
        await db.execute("""
            CREATE TABLE project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK(status IN ('todo','in_progress','done')),
                due_date TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            f"INSERT INTO project_tasks ({cols_csv}) SELECT {cols_csv} FROM project_tasks_broken"
        )
        await db.execute("DROP TABLE project_tasks_broken")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id)"
        )
        await db.execute("PRAGMA legacy_alter_table=OFF")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        logger.info("Миграция: FK в project_tasks починен")


async def _migrate_fix_projects_fk() -> None:
    """Починить FK у projects: client_id REFERENCES clients_old → clients.

    PRAGMA legacy_alter_table=ON — критично: без неё SQLite 3.25+ переписывает
    FK-ссылки в зависимых таблицах при ALTER ... RENAME, из-за чего ссылки
    на временное имя projects_broken становятся висячими после DROP.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='projects'"
        )
        row = await cur.fetchone()
        if not row or not row[0] or "clients_old" not in row[0]:
            return
        logger.info("Миграция: чиним FK в projects (clients_old → clients)...")
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute("PRAGMA legacy_alter_table=ON")
        cur = await db.execute("PRAGMA table_info(projects)")
        old_cols = [r[1] for r in await cur.fetchall()]
        cols_csv = ", ".join(old_cols)
        await db.execute("ALTER TABLE projects RENAME TO projects_broken")
        await db.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'discovery',
                progress INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                deadline TEXT,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                executor TEXT DEFAULT '',
                executor_type TEXT DEFAULT '',
                contractor TEXT DEFAULT '',
                budget REAL DEFAULT 0,
                spent REAL DEFAULT 0,
                health_score INTEGER DEFAULT 100,
                health_issues TEXT DEFAULT '[]',
                priority TEXT DEFAULT 'средний',
                tags TEXT DEFAULT '[]',
                links TEXT DEFAULT '[]',
                checklist TEXT DEFAULT '[]',
                risk_level TEXT DEFAULT 'низкий',
                notes TEXT DEFAULT ''
            )
        """)
        await db.execute(
            f"INSERT INTO projects ({cols_csv}) SELECT {cols_csv} FROM projects_broken"
        )
        await db.execute("DROP TABLE projects_broken")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client_id)"
        )
        await db.execute("PRAGMA legacy_alter_table=OFF")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        logger.info("Миграция: FK в projects починен")


async def _migrate_fix_payments_fk() -> None:
    """Починить FK у payments: client_id REFERENCES clients_old → clients."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='payments'"
        )
        row = await cur.fetchone()
        if not row or not row[0] or "clients_old" not in row[0]:
            return
        logger.info("Миграция: чиним FK в payments (clients_old → clients)...")
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute("PRAGMA legacy_alter_table=ON")
        cur = await db.execute("PRAGMA table_info(payments)")
        old_cols = [r[1] for r in await cur.fetchall()]
        cols_csv = ", ".join(old_cols)
        await db.execute("ALTER TABLE payments RENAME TO payments_broken")
        await db.execute("""
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'ожидается',
                description TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                paid_date TEXT DEFAULT '',
                invoice_number TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            f"INSERT INTO payments ({cols_csv}) SELECT {cols_csv} FROM payments_broken"
        )
        await db.execute("DROP TABLE payments_broken")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_client ON payments(client_id)"
        )
        await db.execute("PRAGMA legacy_alter_table=OFF")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        logger.info("Миграция: FK в payments починен")


async def _migrate_drop_legacy_tables() -> None:
    """Удалить хвостовые _old/_broken таблицы после успешной миграции CHECK/FK."""
    legacy = (
        "clients_old", "projects_old",
        "project_tasks_broken", "projects_broken", "payments_broken",
    )
    async with aiosqlite.connect(str(DB_PATH)) as db:
        for tbl in legacy:
            cur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            )
            if await cur.fetchone():
                await db.execute(f"DROP TABLE IF EXISTS {tbl}")
                logger.info("Миграция: удалена устаревшая таблица %s", tbl)
        await db.commit()


async def create_task(owner_message: str) -> int:
    """Создать новую задачу, вернуть task_id."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO tasks (owner_message) VALUES (?)",
            (owner_message,)
        )
        await db.commit()
        task_id = cursor.lastrowid
        logger.info("Создана задача #%d", task_id)
        return task_id
    finally:
        await db.close()


async def update_task(
    task_id: int,
    status: str | None = None,
    result: str | None = None,
    error: str | None = None,
    duration: float | None = None,
):
    """Обновить поля задачи (только переданные)."""
    db = await _get_db()
    try:
        fields = []
        values = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if result is not None:
            fields.append("result = ?")
            values.append(result)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if duration is not None:
            fields.append("duration_seconds = ?")
            values.append(duration)
        if not fields:
            return
        values.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
        await db.execute(sql, values)
        await db.commit()
        logger.info("Задача #%d обновлена: %s", task_id, ", ".join(fields))
    finally:
        await db.close()


async def add_execution(
    task_id: int,
    agent_name: str,
    agent_role: str,
    input_brief: str,
    output_text: str | None = None,
    tokens: int = 0,
    parent_agent: str | None = None,
    status: str = "done",
) -> int:
    """Добавить запись выполнения агентом, вернуть execution_id."""
    db = await _get_db()
    try:
        completed = datetime.utcnow().isoformat() if status == "done" else None
        cursor = await db.execute(
            """INSERT INTO agent_executions
               (task_id, agent_name, agent_role, input_brief, output_text,
                status, tokens_used, completed_at, parent_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, agent_name, agent_role, input_brief, output_text,
             status, tokens, completed, parent_agent),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_task_chain(task_id: int) -> list[dict]:
    """Вернуть все выполнения по задаче в хронологическом порядке."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM agent_executions
               WHERE task_id = ? ORDER BY created_at ASC""",
            (task_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_task(task_id: int) -> dict | None:
    """Получить одну задачу по ID."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_tasks(limit: int = 20, offset: int = 0) -> list[dict]:
    """Список задач, последние первые."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_content(
    status: str | None = None,
    channel: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Получить контент с опциональными фильтрами."""
    db = await _get_db()
    try:
        conditions = []
        params: list = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if channel:
            conditions.append("channel = ?")
            params.append(channel)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cursor = await db.execute(
            f"SELECT * FROM content {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_content_by_id(content_id: int) -> dict | None:
    """Получить единицу контента по ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM content WHERE id = ?", (content_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def save_content(
    task_id: int | None,
    channel: str,
    topic: str,
    body: str,
    rubric: str | None = None,
) -> int:
    """Сохранить единицу контента, вернуть content_id."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO content (task_id, channel, topic, body, rubric)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, channel, topic, body, rubric),
        )
        await db.commit()
        content_id = cursor.lastrowid
        logger.info("Контент #%d сохранён (канал=%s)", content_id, channel)
        return content_id
    finally:
        await db.close()


async def update_content_status(
    content_id: int,
    status: str,
    qa_notes: str | None = None,
):
    """Обновить статус контента и QA заметки."""
    db = await _get_db()
    try:
        fields = ["status = ?"]
        values: list = [status]
        if qa_notes is not None:
            fields.append("qa_notes = ?")
            values.append(qa_notes)
        if status == "approved":
            fields.append("qa_passed = 1")
        if status == "published":
            fields.append("published_at = datetime('now')")
        values.append(content_id)
        sql = f"UPDATE content SET {', '.join(fields)} WHERE id = ?"
        await db.execute(sql, values)
        await db.commit()
        logger.info("Контент #%d → %s", content_id, status)
    finally:
        await db.close()


async def get_metrics() -> dict:
    """Метрики за сегодня и за всё время."""
    db = await _get_db()
    try:
        today = date.today().isoformat()

        cur = await db.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE date(created_at) = ?", (today,)
        )
        today_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            """SELECT COUNT(*) FROM tasks
               WHERE status = 'done' AND date(created_at) = ?""",
            (today,),
        )
        today_done_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'done'"
        )
        done_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'error'"
        )
        error_tasks = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM content")
        total_content = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM content WHERE status = 'published'"
        )
        published_content = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) FROM agent_executions"
        )
        total_tokens = (await cur.fetchone())[0]

        cur = await db.execute(
            """SELECT COALESCE(SUM(tokens_used), 0) FROM agent_executions
               WHERE date(created_at) = ?""",
            (today,),
        )
        today_tokens = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM agent_executions")
        total_executions = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COALESCE(AVG(duration_seconds), 0) FROM tasks WHERE status = 'done'"
        )
        avg_duration = round((await cur.fetchone())[0], 1)

        return {
            "total_tasks": total_tasks,
            "today_tasks": today_tasks,
            "today_done_tasks": today_done_tasks,
            "done_tasks": done_tasks,
            "error_tasks": error_tasks,
            "total_content": total_content,
            "published_content": published_content,
            "total_tokens": total_tokens,
            "today_tokens": today_tokens,
            "total_executions": total_executions,
            "avg_duration_seconds": avg_duration,
        }
    finally:
        await db.close()


async def save_report(
    period_type: str,
    period_start: str,
    summary_json: dict,
) -> int:
    """Сохранить отчёт, вернуть report_id."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO reports (period_type, period_start, summary_json)
               VALUES (?, ?, ?)""",
            (period_type, period_start, json.dumps(summary_json, ensure_ascii=False)),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_content_for_task(task_id: int) -> list[dict]:
    """Получить весь контент, связанный с задачей."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM content WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════
# HQ: CRUD для клиентов, проектов, учеников
# ═══════════════════════════════════════════════════════════════

async def get_clients(status: str | None = None, include_archived: bool = False) -> list[dict]:
    db = await _get_db()
    try:
        cond = []
        params: list = []
        if not include_archived:
            cond.append("COALESCE(is_archived, 0) = 0")
        if status:
            cond.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        cur = await db.execute(f"SELECT * FROM clients {where} ORDER BY created_at DESC", params)
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def archive_client(client_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("UPDATE clients SET is_archived = 1 WHERE id = ? AND COALESCE(is_archived, 0) = 0", (client_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def restore_client(client_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("UPDATE clients SET is_archived = 0 WHERE id = ? AND is_archived = 1", (client_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def get_archived_clients() -> list[dict]:
    return await get_clients(include_archived=True)


async def get_client(client_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


_CLIENT_INSERT_COLS = [
    "name", "company", "contact", "service_type", "status",
    "start_date", "end_date", "total_amount", "paid_amount",
    "next_action", "next_action_date", "notes",
    "source", "source_detail", "tags", "segment", "inn", "requisites", "links",
    "status_ru", "payment_status", "contract_number", "contract_date",
    "custom_fields", "responsible", "priority",
]


async def create_client(data: dict) -> int:
    db = await _get_db()
    try:
        defaults = {
            "source": "",
            "source_detail": "",
            "tags": "[]",
            "segment": "",
            "inn": "",
            "requisites": "",
            "links": "[]",
            "status_ru": "Лид",
            "payment_status": "не выставлено",
            "contract_number": "",
            "contract_date": "",
            "custom_fields": "{}",
            "responsible": "",
            "priority": "средний",
        }
        cols = _CLIENT_INSERT_COLS
        vals = [data.get(c, defaults.get(c)) if c in defaults else data.get(c) for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        cur = await db.execute(
            f"INSERT INTO clients ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        await db.commit()
        cid = cur.lastrowid
        try:
            await insert_timeline_event(
                "client", cid, "создан", "Клиент создан",
                meta={"name": data.get("name")}, created_by="owner",
            )
        except Exception:
            logger.exception("timeline client create")
        return cid
    finally:
        await db.close()


async def update_client(client_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"name", "company", "contact", "service_type", "status",
                   "start_date", "end_date", "total_amount", "paid_amount",
                   "next_action", "next_action_date", "notes",
                   "source", "source_detail", "tags", "segment", "inn", "requisites", "links",
                   "status_ru", "payment_status", "contract_number", "contract_date",
                   "custom_fields", "responsible", "priority"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        old = await get_client(client_id)
        sql = f"UPDATE clients SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [client_id])
        await db.commit()
        try:
            if old and "status" in data and data.get("status") != old.get("status"):
                await insert_timeline_event(
                    "client",
                    client_id,
                    "изменён",
                    f"Статус: {old.get('status')} → {data.get('status')}",
                    created_by="owner",
                )
        except Exception:
            logger.exception("timeline client update")
        return True
    finally:
        await db.close()


async def delete_client(client_id: int, cascade: bool = True) -> bool:
    """Удалить клиента. cascade=True удаляет связанные проекты, платежи, задачи."""
    db = await _get_db()
    try:
        if cascade:
            # Удалить задачи проектов → проекты
            cur_p = await db.execute("SELECT id FROM projects WHERE client_id = ?", (client_id,))
            proj_ids = [r[0] for r in await cur_p.fetchall()]
            for pid in proj_ids:
                await db.execute("DELETE FROM project_tasks WHERE project_id = ?", (pid,))
            await db.execute("DELETE FROM projects WHERE client_id = ?", (client_id,))
            await db.execute("DELETE FROM payments WHERE client_id = ?", (client_id,))
            await db.execute("DELETE FROM tasks_v2 WHERE client_id = ?", (client_id,))
            await db.execute("DELETE FROM timeline_events WHERE entity_type = 'client' AND entity_id = ?", (client_id,))
        cur = await db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def get_projects(client_id: int | None = None) -> list[dict]:
    db = await _get_db()
    try:
        if client_id:
            cur = await db.execute(
                "SELECT p.*, c.name as client_name FROM projects p LEFT JOIN clients c ON p.client_id = c.id WHERE p.client_id = ? ORDER BY p.created_at DESC",
                (client_id,))
        else:
            cur = await db.execute(
                "SELECT p.*, c.name as client_name FROM projects p LEFT JOIN clients c ON p.client_id = c.id ORDER BY p.created_at DESC")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def create_project(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO projects
               (client_id, name, stage, progress, description, deadline,
                executor, budget, priority, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get("client_id"), data["name"], data.get("stage", "discovery"),
             data.get("progress", 0), data.get("description"), data.get("deadline"),
             data.get("executor", ""), float(data.get("budget", 0) or 0),
             data.get("priority", "средний"), data.get("notes", ""))
        )
        await db.commit()
        pid = cur.lastrowid
        try:
            await insert_timeline_event(
                "project", pid, "создан", f"Проект: {data.get('name', '')}",
                meta={"client_id": data.get("client_id")}, created_by="owner",
            )
            cid = data.get("client_id")
            if cid is not None:
                await insert_timeline_event(
                    "client",
                    int(cid),
                    "этап",
                    f"Новый проект: {data.get('name', '')}",
                    meta={"project_id": pid},
                    created_by="owner",
                )
        except Exception:
            logger.exception("timeline project create")
        return pid
    finally:
        await db.close()


async def update_project(project_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {
            "client_id", "name", "stage", "progress", "description", "deadline", "is_done",
            "executor", "executor_type", "contractor", "budget", "spent",
            "health_score", "health_issues", "priority", "tags", "links",
            "checklist", "risk_level", "notes",
        }
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        old = await get_project(project_id)
        fields.append(("updated_at", datetime.utcnow().isoformat()))
        sql = f"UPDATE projects SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [project_id])
        await db.commit()
        try:
            if old and "stage" in data and data.get("stage") != old.get("stage"):
                await insert_timeline_event(
                    "project",
                    project_id,
                    "этап",
                    f"Этап: {old.get('stage')} → {data.get('stage')}",
                    created_by="owner",
                )
        except Exception:
            logger.exception("timeline project update")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(calculate_health_score(project_id))
        except RuntimeError:
            pass
        return True
    finally:
        await db.close()


async def get_project_tasks(project_id: int) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM project_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,))
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def create_project_task(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            "INSERT INTO project_tasks (project_id, title, status, due_date) VALUES (?, ?, ?, ?)",
            (data["project_id"], data["title"], data.get("status", "todo"), data.get("due_date"))
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_project_task(task_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"title", "status", "due_date"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if data.get("status") == "done":
            fields.append(("completed_at", datetime.utcnow().isoformat()))
        if not fields:
            return False
        sql = f"UPDATE project_tasks SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [task_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def get_students(status: str | None = None) -> list[dict]:
    db = await _get_db()
    try:
        if status:
            cur = await db.execute("SELECT * FROM students WHERE status = ? ORDER BY created_at DESC", (status,))
        else:
            cur = await db.execute("SELECT * FROM students ORDER BY created_at DESC")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_student(student_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_student(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO students (
                name, contact, program, start_date,
                total_sessions, completed_sessions, payment_total, payment_received,
                next_session_date, progress_notes, status, client_id,
                revenue_type, student_total, student_paid, student_percent,
                expense_total, expense_paid, notes, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["name"],
                data.get("contact"),
                data.get("program"),
                data.get("start_date"),
                data.get("total_sessions", 0),
                data.get("completed_sessions", 0),
                data.get("payment_total", 0),
                data.get("payment_received", 0),
                data.get("next_session_date"),
                data.get("progress_notes"),
                data.get("status", "active"),
                data.get("client_id"),
                data.get("revenue_type") or "agency",
                float(data.get("student_total") or 0),
                float(data.get("student_paid") or 0),
                float(data.get("student_percent") or 0),
                float(data.get("expense_total") or 0),
                float(data.get("expense_paid") or 0),
                data.get("notes") or "",
                data.get("source") or "",
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_student(student_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"name", "contact", "program", "start_date", "total_sessions",
                   "completed_sessions", "payment_total", "payment_received",
                   "next_session_date", "progress_notes", "status", "client_id",
                   "revenue_type", "student_total", "student_paid", "student_percent",
                   "expense_total", "expense_paid", "notes", "source"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        sql = f"UPDATE students SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [student_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def get_student_tasks(student_id: int) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM student_tasks WHERE student_id = ? ORDER BY created_at DESC",
            (student_id,))
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def create_student_task(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO student_tasks (student_id, title, description, due_date, status)
               VALUES (?, ?, ?, ?, ?)""",
            (data["student_id"], data["title"], data.get("description"),
             data.get("due_date"), data.get("status", "assigned"))
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_student_task(task_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"title", "description", "due_date", "status", "feedback", "grade"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        sql = f"UPDATE student_tasks SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [task_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def get_deadlines(days: int = 14) -> list[dict]:
    """Все дедлайны на N дней вперёд."""
    db = await _get_db()
    try:
        results = []
        cur = await db.execute(
            """SELECT p.id, p.name, p.deadline, p.stage, c.name as client_name
               FROM projects p JOIN clients c ON p.client_id = c.id
               WHERE p.deadline IS NOT NULL AND p.is_done = 0
               AND date(p.deadline) <= date('now', '+' || ? || ' days')
               ORDER BY p.deadline ASC""", (days,))
        for r in await cur.fetchall():
            d = dict(r)
            d["type"] = "project"
            results.append(d)

        cur = await db.execute(
            """SELECT id, title, due_date, project_id FROM project_tasks
               WHERE due_date IS NOT NULL AND status != 'done'
               AND date(due_date) <= date('now', '+' || ? || ' days')
               ORDER BY due_date ASC""", (days,))
        for r in await cur.fetchall():
            d = dict(r)
            d["type"] = "task"
            results.append(d)

        cur = await db.execute(
            """SELECT id, title, due_date, student_id FROM student_tasks
               WHERE due_date IS NOT NULL AND status NOT IN ('done','reviewed')
               AND date(due_date) <= date('now', '+' || ? || ' days')
               ORDER BY due_date ASC""", (days,))
        for r in await cur.fetchall():
            d = dict(r)
            d["type"] = "student_task"
            results.append(d)

        return results
    finally:
        await db.close()


async def get_daily_reports(limit: int = 10) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM daily_reports ORDER BY date DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def save_daily_report(date_str: str, content_json: str) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            "INSERT INTO daily_reports (date, content_json) VALUES (?, ?)",
            (date_str, content_json))
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_business_metrics() -> dict:
    """Бизнес-метрики из таблиц clients/students."""
    db = await _get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) FROM clients WHERE status = 'active'")
        active_clients = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM clients WHERE status = 'lead'")
        leads = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM students WHERE status = 'active'")
        active_students = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM clients")
        total_revenue = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COALESCE(SUM(paid_amount), 0) FROM clients")
        total_paid = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COALESCE(SUM(total_amount - paid_amount), 0) FROM clients WHERE total_amount > paid_amount")
        pending_payments = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COALESCE(SUM(payment_total - payment_received), 0) FROM students WHERE payment_total > payment_received")
        student_debt = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COALESCE(SUM(payment_received), 0) FROM students")
        student_revenue = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM projects WHERE is_done = 0")
        active_projects = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM project_tasks WHERE status != 'done'")
        open_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM student_tasks WHERE status IN ('assigned','submitted')")
        pending_student_tasks = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT AVG(total_amount) FROM clients WHERE total_amount > 0"
        )
        avg_check = round((await cur.fetchone())[0] or 0, 2)

        cur = await db.execute(
            "SELECT AVG(total_amount) FROM clients WHERE status = 'active' AND total_amount > 0"
        )
        ltv_approx = round((await cur.fetchone())[0] or 0, 2)

        converted = active_clients + leads
        lead_to_client_rate = (
            round(active_clients / converted, 4) if converted else 0.0
        )

        cur = await db.execute(
            """SELECT service_type, COUNT(*) as c FROM clients
               GROUP BY service_type ORDER BY c DESC"""
        )
        service_load = [{"service_type": r[0] or "—", "count": r[1]} for r in await cur.fetchall()]

        cur = await db.execute(
            """SELECT strftime('%Y-%m', COALESCE(NULLIF(start_date,''), created_at)) as ym,
                      SUM(paid_amount) as paid
               FROM clients
               GROUP BY ym
               ORDER BY ym DESC
               LIMIT 12"""
        )
        revenue_by_month = [
            {"month": r[0] or "—", "paid": float(r[1] or 0)} for r in await cur.fetchall()
        ]

        return {
            "active_clients": active_clients,
            "leads": leads,
            "active_students": active_students,
            "total_revenue": total_revenue,
            "total_paid": total_paid,
            "pending_payments": pending_payments,
            "student_debt": student_debt,
            "student_revenue": student_revenue,
            "active_projects": active_projects,
            "open_tasks": open_tasks,
            "pending_student_tasks": pending_student_tasks,
            "avg_check": avg_check,
            "ltv_active_avg": ltv_approx,
            "lead_to_client_rate": lead_to_client_rate,
            "service_load": service_load,
            "revenue_by_month": list(reversed(revenue_by_month)),
        }
    finally:
        await db.close()


async def count_tasks_due_today() -> int:
    """Задачи (проект + ученики) с дедлайном сегодня и не закрытые."""
    db = await _get_db()
    try:
        today = date.today().isoformat()
        cur = await db.execute(
            """SELECT COUNT(*) FROM project_tasks
               WHERE date(due_date) = date(?) AND status != 'done'""",
            (today,),
        )
        n1 = (await cur.fetchone())[0]
        cur = await db.execute(
            """SELECT COUNT(*) FROM student_tasks
               WHERE date(due_date) = date(?) AND status NOT IN ('done','reviewed')""",
            (today,),
        )
        n2 = (await cur.fetchone())[0]
        cur = await db.execute(
            """SELECT COUNT(*) FROM clients
               WHERE next_action_date IS NOT NULL AND date(next_action_date) = date(?)""",
            (today,),
        )
        n3 = (await cur.fetchone())[0]
        return int(n1 + n2 + n3)
    finally:
        await db.close()


async def add_hq_message(agent_name: str, role: str, content: str) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            "INSERT INTO hq_agent_messages (agent_name, role, content) VALUES (?, ?, ?)",
            (agent_name, role, content[:100000]),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_hq_messages(agent_name: str, limit: int = 80) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT * FROM hq_agent_messages WHERE agent_name = ?
               ORDER BY created_at ASC LIMIT ?""",
            (agent_name, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_reminders_due(
    include_sent: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    db = await _get_db()
    try:
        cond = []
        params: list = []
        if not include_sent:
            cond.append("is_sent = 0")
        if from_date:
            cond.append("date(scheduled_for) >= date(?)")
            params.append(from_date)
        if to_date:
            cond.append("date(scheduled_for) <= date(?)")
            params.append(to_date)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        cur = await db.execute(
            f"SELECT * FROM reminders {where} ORDER BY scheduled_for ASC",
            params,
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def update_reminder_sent(reminder_id: int, is_sent: int = 1) -> bool:
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE reminders SET is_sent = ? WHERE id = ?",
            (is_sent, reminder_id),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def create_reminder_row(
    type_: str,
    related_id: int | None,
    text: str,
    scheduled_for: str,
) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO reminders (type, related_id, text, scheduled_for)
               VALUES (?, ?, ?, ?)""",
            (type_, related_id, text, scheduled_for),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_metrics_cache_rows(metric_prefix: str | None = None) -> list[dict]:
    db = await _get_db()
    try:
        if metric_prefix:
            cur = await db.execute(
                "SELECT * FROM metrics_cache WHERE metric_name LIKE ? ORDER BY updated_at DESC",
                (f"{metric_prefix}%",),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM metrics_cache ORDER BY updated_at DESC LIMIT 200"
            )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def upsert_metrics_cache(metric_name: str, value: str, date_str: str | None = None) -> None:
    db = await _get_db()
    try:
        d = date_str or date.today().isoformat()
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "SELECT id FROM metrics_cache WHERE metric_name = ? AND date = ?",
            (metric_name, d),
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                "UPDATE metrics_cache SET value = ?, updated_at = ? WHERE id = ?",
                (value, now, row[0]),
            )
        else:
            await db.execute(
                """INSERT INTO metrics_cache (metric_name, value, date, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (metric_name, value, d, now),
            )
        await db.commit()
    finally:
        await db.close()


async def get_daily_report_by_id(report_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM daily_reports WHERE id = ?", (report_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_project(project_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT p.*, c.name as client_name FROM projects p
               LEFT JOIN clients c ON p.client_id = c.id WHERE p.id = ?""",
            (project_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_app_setting(key: str) -> str | None:
    """Простой key-value слой для настроек HQ (и др.)."""
    await ensure_app_settings_table()
    db = await _get_db()
    try:
        cur = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None
    finally:
        await db.close()


async def set_app_setting(key: str, value: str) -> None:
    await ensure_app_settings_table()
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = datetime('now')
            """,
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════
# HQ: личные заметки владельца (owner_notes)
# ═══════════════════════════════════════════════════════════════


async def list_owner_notes() -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM owner_notes ORDER BY datetime(created_at) DESC, id DESC"
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_owner_note(note_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM owner_notes WHERE id = ?", (note_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_owner_note(text: str, priority: str = "normal") -> dict:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO owner_notes (text, priority)
               VALUES (?, ?)""",
            (text, priority),
        )
        await db.commit()
        nid = cur.lastrowid
        cur2 = await db.execute("SELECT * FROM owner_notes WHERE id = ?", (nid,))
        row = await cur2.fetchone()
        return dict(row) if row else {}
    finally:
        await db.close()


async def update_owner_note(
    note_id: int,
    text: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> dict | None:
    db = await _get_db()
    try:
        fields: list[str] = []
        values: list = []
        if text is not None:
            fields.append("text = ?")
            values.append(text)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if priority is not None:
            fields.append("priority = ?")
            values.append(priority)
        if not fields:
            cur = await db.execute("SELECT * FROM owner_notes WHERE id = ?", (note_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
        now = datetime.utcnow().isoformat()
        fields.append("updated_at = ?")
        values.append(now)
        values.append(note_id)
        sql = f"UPDATE owner_notes SET {', '.join(fields)} WHERE id = ?"
        await db.execute(sql, values)
        await db.commit()
        cur = await db.execute("SELECT * FROM owner_notes WHERE id = ?", (note_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def delete_owner_note(note_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM owner_notes WHERE id = ?", (note_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def owner_note_mark_sent_to_team(note_id: int, task_id: int) -> bool:
    db = await _get_db()
    try:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            """UPDATE owner_notes
               SET sent_to_team = 1, task_id = ?, status = 'queued', updated_at = ?
               WHERE id = ? AND COALESCE(sent_to_team, 0) = 0""",
            (task_id, now, note_id),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════
# HQ v3.0 — миграция и хелперы
# ═══════════════════════════════════════════════════════════════


async def _table_column_names(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {str(r[1]) for r in rows}


async def _add_column_if_missing(
    db: aiosqlite.Connection, table: str, column: str, decl: str
) -> None:
    if column in await _table_column_names(db, table):
        return
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


async def _migrate_projects_nullable_client_id(db: aiosqlite.Connection) -> None:
    """Проект без клиента: client_id может быть NULL (пересборка таблицы в SQLite)."""
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
    )
    if not await cur.fetchone():
        return
    cur = await db.execute("PRAGMA table_info(projects)")
    rows = await cur.fetchall()
    client_row = next((r for r in rows if r[1] == "client_id"), None)
    if not client_row or int(client_row[3]) == 0:
        return

    await db.execute("PRAGMA foreign_keys=OFF")
    await db.execute("DROP INDEX IF EXISTS idx_projects_client")
    await db.execute("ALTER TABLE projects RENAME TO projects_old")
    await db.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'discovery'
                CHECK(stage IN ('discovery','design','development','testing','launch','support')),
            progress INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            deadline TEXT,
            is_done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            executor TEXT DEFAULT '',
            executor_type TEXT DEFAULT '',
            contractor TEXT DEFAULT '',
            budget REAL DEFAULT 0,
            spent REAL DEFAULT 0,
            health_score INTEGER DEFAULT 100,
            health_issues TEXT DEFAULT '[]',
            priority TEXT DEFAULT 'средний',
            tags TEXT DEFAULT '[]',
            links TEXT DEFAULT '[]',
            checklist TEXT DEFAULT '[]',
            risk_level TEXT DEFAULT 'низкий',
            notes TEXT DEFAULT ''
        )
        """
    )
    cur = await db.execute("PRAGMA table_info(projects)")
    new_cols = [r[1] for r in await cur.fetchall()]
    cur = await db.execute("PRAGMA table_info(projects_old)")
    old_names = {r[1] for r in await cur.fetchall()}
    common = [c for c in new_cols if c in old_names]
    if common:
        q = ", ".join(f'"{c}"' for c in common)
        await db.execute(f"INSERT INTO projects ({q}) SELECT {q} FROM projects_old")
    await db.execute("DROP TABLE projects_old")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client_id)")
    await db.execute("PRAGMA foreign_keys=ON")


async def _migrate_tasks_v2_delegation(db: aiosqlite.Connection) -> None:
    """Колонки делегирования tasks_v2 + чеклист и комментарии (идемпотентно)."""
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks_v2'"
    )
    if not await cur.fetchone():
        return
    for col, decl in [
        ("assignee_id", "INTEGER"),
        ("goal", "TEXT DEFAULT ''"),
        ("result", "TEXT DEFAULT ''"),
    ]:
        await _add_column_if_missing(db, "tasks_v2", col, decl)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks_v2_checklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            is_completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks_v2(id) ON DELETE CASCADE
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks_v2_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER DEFAULT NULL,
            author_name TEXT DEFAULT '',
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks_v2(id) ON DELETE CASCADE
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_v2_assignee ON tasks_v2(assignee_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_v2_checklist_task ON tasks_v2_checklist(task_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_v2_comments_task ON tasks_v2_comments(task_id)"
    )
    logger.info("Migration: tasks_v2 delegation fields added")


async def _migrate_students_extended(db: aiosqlite.Connection) -> None:
    """Расширяет таблицу students: доход и расходы; проекты и расходы ученика."""
    new_cols = [
        ("revenue_type", "TEXT DEFAULT 'agency'"),
        ("student_total", "REAL DEFAULT 0"),
        ("student_paid", "REAL DEFAULT 0"),
        ("student_percent", "REAL DEFAULT 0"),
        ("expense_total", "REAL DEFAULT 0"),
        ("expense_paid", "REAL DEFAULT 0"),
        ("notes", "TEXT DEFAULT ''"),
        ("source", "TEXT DEFAULT ''"),
    ]
    for col, definition in new_cols:
        try:
            await db.execute(f"ALTER TABLE students ADD COLUMN {col} {definition}")
        except Exception:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS student_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'В работе',
            total_amount REAL DEFAULT 0,
            our_percent REAL DEFAULT 0,
            our_amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            revenue_type TEXT DEFAULT 'student',
            deadline TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS student_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount REAL DEFAULT 0,
            paid INTEGER DEFAULT 0,
            date TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_projects_student ON student_projects(student_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_expenses_student ON student_expenses(student_id)"
    )
    logger.info("Migration: students extended fields added")


async def _migrate_delivery_projects_student(db: aiosqlite.Connection) -> None:
    """Поля ученика и доли для delivery_projects."""
    for col, definition in [
        ("student_id", "INTEGER DEFAULT NULL"),
        ("owner_type", "TEXT DEFAULT 'agency'"),
        ("our_percent", "REAL DEFAULT 0"),
        ("our_amount", "REAL DEFAULT 0"),
        ("notes", "TEXT DEFAULT ''"),
    ]:
        try:
            await db.execute(f"ALTER TABLE delivery_projects ADD COLUMN {col} {definition}")
        except Exception:
            pass
    logger.info("Migration: delivery_projects student fields added")


async def _migrate_v3() -> None:
    """Расширение схемы v3: новые колонки и таблицы без удаления данных."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        await _add_column_if_missing(db, "clients", "is_archived", "INTEGER DEFAULT 0")

        for col, decl in [
            ("source", "TEXT DEFAULT ''"),
            ("source_detail", "TEXT DEFAULT ''"),
            ("tags", "TEXT DEFAULT '[]'"),
            ("segment", "TEXT DEFAULT ''"),
            ("inn", "TEXT DEFAULT ''"),
            ("requisites", "TEXT DEFAULT ''"),
            ("links", "TEXT DEFAULT '[]'"),
            ("status_ru", "TEXT DEFAULT 'Лид'"),
            ("payment_status", "TEXT DEFAULT 'не выставлено'"),
            ("contract_number", "TEXT DEFAULT ''"),
            ("contract_date", "TEXT DEFAULT ''"),
            ("custom_fields", "TEXT DEFAULT '{}'"),
            ("responsible", "TEXT DEFAULT ''"),
            ("priority", "TEXT DEFAULT 'средний'"),
        ]:
            await _add_column_if_missing(db, "clients", col, decl)

        for col, decl in [
            ("executor", "TEXT DEFAULT ''"),
            ("executor_type", "TEXT DEFAULT ''"),
            ("contractor", "TEXT DEFAULT ''"),
            ("budget", "REAL DEFAULT 0"),
            ("spent", "REAL DEFAULT 0"),
            ("health_score", "INTEGER DEFAULT 100"),
            ("health_issues", "TEXT DEFAULT '[]'"),
            ("priority", "TEXT DEFAULT 'средний'"),
            ("tags", "TEXT DEFAULT '[]'"),
            ("links", "TEXT DEFAULT '[]'"),
            ("checklist", "TEXT DEFAULT '[]'"),
            ("risk_level", "TEXT DEFAULT 'низкий'"),
            ("notes", "TEXT DEFAULT ''"),
        ]:
            await _add_column_if_missing(db, "projects", col, decl)

        await _add_column_if_missing(db, "students", "client_id", "INTEGER")
        await _add_column_if_missing(db, "kanban_notes", "due_date", "TEXT DEFAULT ''")
        await _add_column_if_missing(
            db, "kanban_notes", "priority", "TEXT DEFAULT 'обычный'"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'ожидается',
                description TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                paid_date TEXT DEFAULT '',
                invoice_number TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                meta TEXT DEFAULT '{}',
                created_by TEXT DEFAULT 'owner',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                type TEXT DEFAULT 'задача',
                status TEXT DEFAULT 'новая',
                priority TEXT DEFAULT 'средний',
                client_id INTEGER,
                project_id INTEGER,
                student_id INTEGER,
                assignee TEXT DEFAULT '',
                agent_initiator TEXT DEFAULT '',
                idea_id INTEGER,
                due_date TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                checklist TEXT DEFAULT '[]',
                tags TEXT DEFAULT '[]',
                repeat_type TEXT DEFAULT '',
                repeat_until TEXT DEFAULT '',
                comments_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, decl in [
            ("execution_date", "TEXT DEFAULT ''"),
            ("deadline", "TEXT DEFAULT ''"),
            ("source", "TEXT DEFAULT ''"),
            ("source_id", "INTEGER"),
            ("ai_task_id", "INTEGER"),
            ("ai_agent_name", "TEXT DEFAULT ''"),
            ("ai_user_message_id", "INTEGER"),
            ("ai_assistant_message_id", "INTEGER"),
            ("ai_last_sync_at", "TEXT DEFAULT ''"),
            ("response_preview", "TEXT DEFAULT ''"),
        ]:
            await _add_column_if_missing(db, "tasks_v2", col, decl)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                source TEXT DEFAULT 'owner',
                agent_name TEXT DEFAULT '',
                status TEXT DEFAULT 'новая',
                task_id INTEGER,
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS kanban_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                column_id TEXT DEFAULT 'inbox',
                color TEXT DEFAULT 'default',
                position INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                linked_task_id INTEGER,
                ai_summary TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                content_text TEXT DEFAULT '',
                chunks TEXT DEFAULT '[]',
                status TEXT DEFAULT 'processing',
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT DEFAULT '',
                entity_type TEXT DEFAULT '',
                entity_id INTEGER,
                is_read INTEGER DEFAULT 0,
                priority TEXT DEFAULT 'обычный',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                content TEXT NOT NULL,
                generated_by TEXT DEFAULT 'ai',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS economics_monthly (
                month TEXT PRIMARY KEY,
                revenue_plan REAL DEFAULT 0,
                revenue_fact REAL DEFAULT 0,
                cash_received REAL DEFAULT 0,
                cash_expected REAL DEFAULT 0,
                expenses_marketing REAL DEFAULT 0,
                expenses_operating REAL DEFAULT 0,
                leads INTEGER DEFAULT 0,
                qualified_leads INTEGER DEFAULT 0,
                clients INTEGER DEFAULT 0,
                avg_check_override REAL DEFAULT 0,
                ltv REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS student_progress_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                action_type TEXT NOT NULL,
                note TEXT DEFAULT '',
                sessions_delta INTEGER DEFAULT 0,
                progress_delta INTEGER DEFAULT 0,
                stage_value TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await _migrate_projects_nullable_client_id(db)

        await _migrate_students_extended(db)

        await _migrate_delivery_projects_student(db)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeline_entity ON timeline_events(entity_type, entity_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_client ON payments(client_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_v2_status ON tasks_v2(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_v2_execution_date ON tasks_v2(execution_date, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_v2_deadline ON tasks_v2(deadline, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_student_progress_logs_student ON student_progress_logs(student_id, created_at)"
        )

        await _migrate_tasks_v2_delegation(db)

        await db.commit()
        logger.info("Миграция HQ v3.0 применена")


async def recalc_client_paid_from_payments(client_id: int) -> float:
    """Сумма оплат со статусом «оплачено» → clients.paid_amount."""
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM payments
               WHERE client_id = ? AND status = 'оплачено'""",
            (client_id,),
        )
        total = float((await cur.fetchone())[0] or 0)
        await db.execute(
            "UPDATE clients SET paid_amount = ? WHERE id = ?",
            (total, client_id),
        )
        await db.commit()
        return total
    finally:
        await db.close()


async def list_payments_for_client(client_id: int) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM payments WHERE client_id = ? ORDER BY datetime(created_at) DESC",
            (client_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_payment(payment_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def insert_payment(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO payments (client_id, amount, status, description, due_date, paid_date, invoice_number)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["client_id"],
                data["amount"],
                data.get("status", "ожидается"),
                data.get("description", ""),
                data.get("due_date", ""),
                data.get("paid_date", ""),
                data.get("invoice_number", ""),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_payment_row(payment_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {
            "amount", "status", "description", "due_date", "paid_date", "invoice_number",
        }
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        sql = f"UPDATE payments SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [payment_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_payment_row(payment_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        row = await cur.fetchone()
        if not row:
            return None
        prev = dict(row)
        await db.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
        await db.commit()
        return prev
    finally:
        await db.close()


async def insert_timeline_event(
    entity_type: str,
    entity_id: int,
    event_type: str,
    title: str,
    description: str = "",
    meta: str | dict | None = None,
    created_by: str = "owner",
) -> int:
    meta_s = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else (meta or "{}")
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO timeline_events
               (entity_type, entity_id, event_type, title, description, meta, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_id, event_type, title, description, meta_s, created_by),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def list_timeline_events(entity_type: str, entity_id: int) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT * FROM timeline_events
               WHERE entity_type = ? AND entity_id = ?
               ORDER BY datetime(created_at) DESC""",
            (entity_type, entity_id),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def list_tasks_v2(
    status: str | None = None,
    client_id: int | None = None,
    priority: str | None = None,
    project_id: int | None = None,
    assignee: str | None = None,
    execution_date: str | None = None,
    month: str | None = None,
    assignee_user_id: int | None = None,
) -> list[dict]:
    """Список задач Kanban с join на клиента, проект и назначенного пользователя hq_users."""
    db = await _get_db()
    try:
        cond = []
        params: list = []

        if assignee_user_id is not None:
            cond.append("t.assignee_id = ?")
            params.append(assignee_user_id)

        if status:
            cond.append("t.status = ?")
            params.append(status)
        if client_id is not None:
            cond.append("t.client_id = ?")
            params.append(client_id)
        if priority:
            cond.append("t.priority = ?")
            params.append(priority)
        if project_id is not None:
            cond.append("t.project_id = ?")
            params.append(project_id)
        if assignee:
            cond.append("t.assignee = ?")
            params.append(assignee)
        if execution_date:
            cond.append(
                "date(COALESCE(NULLIF(t.execution_date, ''), NULLIF(t.deadline, ''), NULLIF(t.due_date, ''))) = date(?)"
            )
            params.append(execution_date)
        if month:
            cond.append(
                "substr(COALESCE(NULLIF(t.execution_date, ''), NULLIF(t.deadline, ''), NULLIF(t.created_at, '')), 1, 7) = ?"
            )
            params.append(month)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        cur = await db.execute(
            f"""SELECT t.*,
                c.name AS client_name,
                p.name AS project_name,
                u.name AS assignee_name
                FROM tasks_v2 t
                LEFT JOIN clients c ON t.client_id = c.id
                LEFT JOIN projects p ON t.project_id = p.id
                LEFT JOIN hq_users u ON t.assignee_id = u.id
                {where}
                ORDER BY
                  CASE t.priority
                    WHEN 'критично' THEN 1
                    WHEN 'высокий' THEN 2
                    WHEN 'средний' THEN 3
                    ELSE 4
                  END,
                  CASE WHEN COALESCE(NULLIF(t.due_date, ''), NULLIF(t.deadline, ''), '') = '' THEN 1 ELSE 0 END,
                  t.due_date ASC,
                  datetime(t.updated_at) DESC, t.id DESC""",
            params,
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_task_v2(task_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM tasks_v2 WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_task_v2_detail(task_id: int) -> dict | None:
    """Одна задача с именами связей и пунктами табличного чеклиста и комментариями."""
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT t.*,
               c.name AS client_name,
               p.name AS project_name,
               u.name AS assignee_name
               FROM tasks_v2 t
               LEFT JOIN clients c ON t.client_id = c.id
               LEFT JOIN projects p ON t.project_id = p.id
               LEFT JOIN hq_users u ON t.assignee_id = u.id
               WHERE t.id = ?""",
            (task_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        task = dict(row)
        chk_legacy = task.pop("checklist", "[]")
        cur = await db.execute(
            "SELECT * FROM tasks_v2_checklist WHERE task_id=? ORDER BY id",
            (task_id,),
        )
        chk_rows = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT * FROM tasks_v2_comments WHERE task_id=? ORDER BY datetime(created_at)",
            (task_id,),
        )
        task["comments"] = [dict(r) for r in await cur.fetchall()]
        task["checklist_legacy_json"] = chk_legacy
        task["checklist"] = chk_rows
        return task
    finally:
        await db.close()


async def insert_task_v2(data: dict) -> int:
    db = await _get_db()
    try:
        execution_date = data.get("execution_date") or data.get("due_date") or ""
        deadline = data.get("deadline") or data.get("due_date") or ""
        due_date = data.get("due_date")
        if due_date is None:
            due_date = deadline or execution_date or ""
        cur = await db.execute(
            """INSERT INTO tasks_v2 (
                title, description, type, status, priority, client_id, project_id, student_id,
                assignee, agent_initiator, idea_id, due_date, checklist, tags, repeat_type, repeat_until,
                execution_date, deadline, source, source_id, ai_task_id, ai_agent_name,
                ai_user_message_id, ai_assistant_message_id, ai_last_sync_at, response_preview,
                assignee_id, goal, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["title"],
                data.get("description", ""),
                data.get("type", "задача"),
                data.get("status", "новая"),
                data.get("priority", "средний"),
                data.get("client_id"),
                data.get("project_id"),
                data.get("student_id"),
                data.get("assignee", ""),
                data.get("agent_initiator", ""),
                data.get("idea_id"),
                due_date,
                data.get("checklist", "[]"),
                data.get("tags", "[]"),
                data.get("repeat_type", ""),
                data.get("repeat_until", ""),
                execution_date,
                deadline,
                data.get("source", ""),
                data.get("source_id"),
                data.get("ai_task_id"),
                data.get("ai_agent_name", ""),
                data.get("ai_user_message_id"),
                data.get("ai_assistant_message_id"),
                data.get("ai_last_sync_at", ""),
                data.get("response_preview", ""),
                data.get("assignee_id"),
                data.get("goal", ""),
                data.get("result", ""),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_task_v2(task_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {
            "title", "description", "type", "status", "priority", "client_id", "project_id",
            "student_id", "assignee", "agent_initiator", "idea_id", "due_date", "completed_at",
            "checklist", "tags", "repeat_type", "repeat_until", "comments_count",
            "execution_date", "deadline", "source", "source_id", "ai_task_id", "ai_agent_name",
            "ai_user_message_id", "ai_assistant_message_id", "ai_last_sync_at", "response_preview",
            "assignee_id", "goal", "result",
        }
        if "due_date" not in data and ("deadline" in data or "execution_date" in data):
            data["due_date"] = data.get("deadline") or data.get("execution_date") or ""
        if "due_date" in data:
            if "deadline" not in data:
                data["deadline"] = data.get("due_date") or ""
            if "execution_date" not in data and not data.get("execution_date"):
                data["execution_date"] = data.get("due_date") or ""
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        fields.append(("updated_at", datetime.utcnow().isoformat()))
        sql = f"UPDATE tasks_v2 SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [task_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_task_v2(task_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM tasks_v2 WHERE id = ?", (task_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def tasks_v2_checklist_task_id_for_item(item_id: int) -> int | None:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT task_id FROM tasks_v2_checklist WHERE id = ?", (item_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None
    finally:
        await db.close()


async def insert_tasks_v2_checklist_item(task_id: int, title: str) -> dict:
    db = await _get_db()
    try:
        cur = await db.execute(
            "INSERT INTO tasks_v2_checklist (task_id, title) VALUES (?, ?)",
            (task_id, title),
        )
        await db.commit()
        iid = cur.lastrowid
        cur = await db.execute(
            "SELECT * FROM tasks_v2_checklist WHERE id = ?", (int(iid),)
        )
        row = await cur.fetchone()
        return dict(row) if row else {}
    finally:
        await db.close()


async def update_tasks_v2_checklist_completed(item_id: int, is_completed: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute(
            "UPDATE tasks_v2_checklist SET is_completed=? WHERE id=?",
            (is_completed, item_id),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def toggle_tasks_v2_checklist_item(item_id: int, is_completed: bool) -> bool:
    """Алиас: bool → is_completed в tasks_v2_checklist."""
    return await update_tasks_v2_checklist_completed(
        item_id, 1 if is_completed else 0
    )


async def delete_tasks_v2_checklist_item(item_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM tasks_v2_checklist WHERE id=?", (item_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def insert_tasks_v2_comment(
    task_id: int, user_id: int | None, author_name: str, body: str
) -> dict:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO tasks_v2_comments (task_id, user_id, author_name, body)
               VALUES (?, ?, ?, ?)""",
            (task_id, user_id, author_name or "", body),
        )
        await db.commit()
        cid = cur.lastrowid
        cur = await db.execute("SELECT * FROM tasks_v2_comments WHERE id = ?", (int(cid),))
        row = await cur.fetchone()
        return dict(row) if row else {}
    finally:
        await db.close()


async def get_tasks_v2_comment(comment_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM tasks_v2_comments WHERE id = ?", (comment_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def delete_tasks_v2_comment(comment_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM tasks_v2_comments WHERE id=?", (comment_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def sync_task_v2_ai_link(
    task_v2_id: int,
    legacy_task_id: int | None = None,
    agent_name: str | None = None,
    user_message_id: int | None = None,
    assistant_message_id: int | None = None,
    response_preview: str | None = None,
    status: str | None = None,
) -> bool:
    payload: dict[str, object] = {
        "ai_last_sync_at": datetime.utcnow().isoformat(),
    }
    if legacy_task_id is not None:
        payload["ai_task_id"] = legacy_task_id
    if agent_name is not None:
        payload["ai_agent_name"] = agent_name
    if user_message_id is not None:
        payload["ai_user_message_id"] = user_message_id
    if assistant_message_id is not None:
        payload["ai_assistant_message_id"] = assistant_message_id
    if response_preview is not None:
        payload["response_preview"] = response_preview[:500]
    if status is not None:
        payload["status"] = status
    return await update_task_v2(task_v2_id, payload)


async def get_team_tasks_history(limit: int = 40) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT
                tv2.*,
                t.status AS ai_status,
                t.result AS ai_result,
                t.error AS ai_error
            FROM tasks_v2 tv2
            LEFT JOIN tasks t ON t.id = tv2.ai_task_id
            WHERE tv2.ai_task_id IS NOT NULL OR COALESCE(tv2.ai_agent_name, '') != ''
            ORDER BY datetime(tv2.updated_at) DESC, tv2.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            result_text = (row.get("ai_result") or row.get("response_preview") or "").strip()
            row["has_response"] = bool(result_text)
            row["response_preview"] = result_text[:500]
            row["open_chat_url"] = (
                f"/hq/team.html?agent={row.get('ai_agent_name') or 'chief_of_staff'}&task={row['id']}"
            )
        return rows
    finally:
        await db.close()


async def list_ideas() -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM ideas ORDER BY datetime(created_at) DESC"
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_idea(idea_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def insert_idea(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO ideas (title, description, source, agent_name, status, tags)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data["title"],
                data.get("description", ""),
                data.get("source", "owner"),
                data.get("agent_name", ""),
                data.get("status", "новая"),
                data.get("tags", "[]"),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_idea_row(idea_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"title", "description", "source", "agent_name", "status", "task_id", "tags"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        sql = f"UPDATE ideas SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [idea_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_idea_row(idea_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def list_kanban_notes(column_id: str | None = None) -> list[dict]:
    db = await _get_db()
    try:
        if column_id:
            cur = await db.execute(
                "SELECT * FROM kanban_notes WHERE column_id = ? ORDER BY position ASC, id ASC",
                (column_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM kanban_notes ORDER BY column_id, position ASC, id ASC"
            )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_kanban_note(note_id: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM kanban_notes WHERE id = ?", (note_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def insert_kanban_note(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO kanban_notes
               (title, content, column_id, color, position, tags, linked_task_id, ai_summary, due_date, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["title"],
                data.get("content", ""),
                data.get("column_id", "inbox"),
                data.get("color", "default"),
                data.get("position", 0),
                data.get("tags", "[]"),
                data.get("linked_task_id"),
                data.get("ai_summary", ""),
                data.get("due_date", ""),
                data.get("priority", "обычный"),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_kanban_note_row(note_id: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {
            "title", "content", "column_id", "color", "position", "tags",
            "linked_task_id", "ai_summary", "due_date", "priority",
        }
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        fields.append(("updated_at", datetime.utcnow().isoformat()))
        sql = f"UPDATE kanban_notes SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [note_id])
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_kanban_note_row(note_id: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM kanban_notes WHERE id = ?", (note_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def list_knowledge_rows() -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM knowledge_base ORDER BY datetime(created_at) DESC"
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_knowledge_row(kid: int) -> dict | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM knowledge_base WHERE id = ?", (kid,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def insert_knowledge_row(data: dict) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO knowledge_base
               (filename, original_name, file_type, file_size, content_text, chunks, status, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["filename"],
                data["original_name"],
                data["file_type"],
                data.get("file_size", 0),
                data.get("content_text", ""),
                data.get("chunks", "[]"),
                data.get("status", "processing"),
                data.get("description", ""),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_knowledge_row(kid: int, data: dict) -> bool:
    db = await _get_db()
    try:
        allowed = {"content_text", "chunks", "status", "description"}
        fields = [(k, v) for k, v in data.items() if k in allowed]
        if not fields:
            return False
        sql = f"UPDATE knowledge_base SET {', '.join(f'{k} = ?' for k, _ in fields)} WHERE id = ?"
        await db.execute(sql, [v for _, v in fields] + [kid])
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_knowledge_row(kid: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute("DELETE FROM knowledge_base WHERE id = ?", (kid,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def search_knowledge_simple(q: str, limit: int = 30) -> list[dict]:
    db = await _get_db()
    try:
        like = f"%{q.strip()}%"
        cur = await db.execute(
            """SELECT id, original_name, file_type, description,
                      SUBSTR(content_text, 1, 400) AS preview
               FROM knowledge_base
               WHERE status = 'ready' AND (
                   content_text LIKE ? OR original_name LIKE ? OR description LIKE ?
               )
               LIMIT ?""",
            (like, like, like, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def insert_notification(
    type_: str,
    title: str,
    message: str = "",
    entity_type: str = "",
    entity_id: int | None = None,
    priority: str = "обычный",
) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """INSERT INTO notifications (type, title, message, entity_type, entity_id, priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (type_, title, message, entity_type, entity_id, priority),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def list_notifications(unread_only: bool = False, limit: int = 50) -> list[dict]:
    db = await _get_db()
    try:
        if unread_only:
            cur = await db.execute(
                """SELECT * FROM notifications WHERE is_read = 0
                   ORDER BY datetime(created_at) DESC LIMIT ?""",
                (limit,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM notifications ORDER BY datetime(created_at) DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def count_unread_notifications() -> int:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0")
        return int((await cur.fetchone())[0])
    finally:
        await db.close()


async def mark_notification_read(nid: int) -> bool:
    db = await _get_db()
    try:
        cur = await db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?", (nid,)
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def mark_all_notifications_read() -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        await db.commit()
    finally:
        await db.close()


def _economics_month_defaults(month: str) -> dict:
    return {
        "month": month,
        "revenue_plan": 0.0,
        "revenue_fact": 0.0,
        "cash_received": 0.0,
        "cash_expected": 0.0,
        "expenses_marketing": 0.0,
        "expenses_operating": 0.0,
        "leads": 0,
        "qualified_leads": 0,
        "clients": 0,
        "avg_check_override": 0.0,
        "ltv": 0.0,
        "notes": "",
    }


def _derive_economics_metrics(payload: dict) -> dict:
    revenue_fact = float(payload.get("revenue_fact") or 0)
    revenue_plan = float(payload.get("revenue_plan") or 0)
    cash_received = float(payload.get("cash_received") or 0)
    cash_expected = float(payload.get("cash_expected") or 0)
    expenses_marketing = float(payload.get("expenses_marketing") or 0)
    expenses_operating = float(payload.get("expenses_operating") or 0)
    leads = int(payload.get("leads") or 0)
    qualified_leads = int(payload.get("qualified_leads") or 0)
    clients = int(payload.get("clients") or 0)
    avg_check_override = float(payload.get("avg_check_override") or 0)
    ltv = float(payload.get("ltv") or 0)

    total_expenses = expenses_marketing + expenses_operating
    profit = revenue_fact - total_expenses
    margin = round((profit / revenue_fact) * 100, 2) if revenue_fact else 0.0
    avg_check = avg_check_override if avg_check_override > 0 else (revenue_fact / clients if clients else 0.0)
    cac = expenses_marketing / clients if clients else 0.0
    roi = round((profit / total_expenses) * 100, 2) if total_expenses else 0.0
    romi = round(((revenue_fact - expenses_marketing) / expenses_marketing) * 100, 2) if expenses_marketing else 0.0
    lead_to_qualified = round((qualified_leads / leads) * 100, 2) if leads else 0.0
    qualified_to_client = round((clients / qualified_leads) * 100, 2) if qualified_leads else 0.0
    lead_to_client = round((clients / leads) * 100, 2) if leads else 0.0
    plan_fact_delta = revenue_fact - revenue_plan
    return {
        "total_expenses": round(total_expenses, 2),
        "profit": round(profit, 2),
        "margin": margin,
        "avg_check": round(avg_check, 2),
        "cac": round(cac, 2),
        "ltv": round(ltv, 2),
        "roi": roi,
        "romi": romi,
        "lead_to_qualified": lead_to_qualified,
        "qualified_to_client": qualified_to_client,
        "lead_to_client": lead_to_client,
        "plan_fact_delta": round(plan_fact_delta, 2),
        "cash_gap": round(cash_expected - cash_received, 2),
    }


async def get_economics_month(month: str) -> dict:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM economics_monthly WHERE month = ?",
            (month,),
        )
        row = await cur.fetchone()
        base = _economics_month_defaults(month)
        if row:
            base.update(dict(row))
        base.update(_derive_economics_metrics(base))
        return base
    finally:
        await db.close()


async def upsert_economics_month(month: str, data: dict) -> dict:
    payload = _economics_month_defaults(month)
    payload.update({k: v for k, v in data.items() if k in payload and k != "month"})
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO economics_monthly (
                month, revenue_plan, revenue_fact, cash_received, cash_expected,
                expenses_marketing, expenses_operating, leads, qualified_leads, clients,
                avg_check_override, ltv, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month) DO UPDATE SET
                revenue_plan = excluded.revenue_plan,
                revenue_fact = excluded.revenue_fact,
                cash_received = excluded.cash_received,
                cash_expected = excluded.cash_expected,
                expenses_marketing = excluded.expenses_marketing,
                expenses_operating = excluded.expenses_operating,
                leads = excluded.leads,
                qualified_leads = excluded.qualified_leads,
                clients = excluded.clients,
                avg_check_override = excluded.avg_check_override,
                ltv = excluded.ltv,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                month,
                payload["revenue_plan"],
                payload["revenue_fact"],
                payload["cash_received"],
                payload["cash_expected"],
                payload["expenses_marketing"],
                payload["expenses_operating"],
                payload["leads"],
                payload["qualified_leads"],
                payload["clients"],
                payload["avg_check_override"],
                payload["ltv"],
                payload["notes"],
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_economics_month(month)


async def list_economics_months(limit: int = 18) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM economics_monthly ORDER BY month DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            row.update(_derive_economics_metrics(row))
        return rows
    finally:
        await db.close()


async def create_student_progress_log(
    student_id: int,
    action_type: str,
    note: str = "",
    sessions_delta: int = 0,
    progress_delta: int = 0,
    project_id: int | None = None,
    stage_value: str = "",
) -> int:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            INSERT INTO student_progress_logs
            (student_id, project_id, action_type, note, sessions_delta, progress_delta, stage_value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, project_id, action_type, note, sessions_delta, progress_delta, stage_value),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def list_student_progress_logs(student_id: int, limit: int = 20) -> list[dict]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT spl.*, p.name AS project_name
            FROM student_progress_logs spl
            LEFT JOIN projects p ON p.id = spl.project_id
            WHERE spl.student_id = ?
            ORDER BY datetime(spl.created_at) DESC, spl.id DESC
            LIMIT ?
            """,
            (student_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def calculate_health_score(project_id: int) -> int:
    """
    Оценка здоровья проекта 0–100. Результат пишется в projects.health_score / health_issues.
    """
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        p = dict(row)
        score = 100
        issues: list[str] = []
        today = date.today()

        dl = p.get("deadline")
        if dl:
            try:
                ds = str(dl)[:10]
                d0 = date.fromisoformat(ds)
                if d0 < today and not p.get("is_done"):
                    score -= 10
                    issues.append("Просрочен дедлайн проекта")
            except ValueError:
                pass

        updated_s = p.get("updated_at")
        if updated_s:
            try:
                from datetime import datetime as dt

                raw = str(updated_s).replace("Z", "")
                if "T" in raw:
                    u = dt.fromisoformat(raw[:19])
                else:
                    u = dt.fromisoformat(str(updated_s)[:10])
                age = (datetime.utcnow() - u).days
                if age >= 7:
                    score -= 15
                    issues.append("Нет активности по проекту 7+ дней")
            except Exception:
                pass

        cur3 = await db.execute(
            """SELECT COUNT(*) FROM project_tasks
               WHERE project_id = ? AND status != 'done' AND due_date IS NOT NULL
               AND date(due_date) < date('now')""",
            (project_id,),
        )
        blockers = int((await cur3.fetchone())[0])
        if blockers > 0:
            score -= 20
            issues.append(f"Просроченные задачи проекта: {blockers}")

        cur4 = await db.execute(
            """SELECT COUNT(*) FROM project_tasks
               WHERE project_id = ? AND status != 'done'""",
            (project_id,),
        )
        open_n = int((await cur4.fetchone())[0])
        cur5 = await db.execute(
            """SELECT COUNT(*) FROM project_tasks
               WHERE project_id = ? AND status = 'done' AND due_date IS NOT NULL
               AND (completed_at IS NULL OR date(completed_at) <= date(due_date))""",
            (project_id,),
        )
        on_time = int((await cur5.fetchone())[0])
        if open_n == 0 and on_time > 0:
            score = min(100, score + 10)

        score = max(0, min(100, score))
        issues_j = json.dumps(issues, ensure_ascii=False)
        await db.execute(
            "UPDATE projects SET health_score = ?, health_issues = ?, updated_at = ? WHERE id = ?",
            (score, issues_j, datetime.utcnow().isoformat(), project_id),
        )
        await db.commit()
        return score
    finally:
        await db.close()


async def format_focus_brief_text() -> str:
    """Текст фокуса дня для Telegram / дашборда."""
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tasks_all = await list_tasks_v2()
    overdue = [
        t for t in tasks_all
        if (t.get("deadline") or t.get("due_date")) and str(t.get("deadline") or t.get("due_date"))[:10] < today
        and (t.get("status") or "") not in ("готово", "отменена")
    ]
    due_today = [
        t for t in tasks_all
        if (t.get("execution_date") or t.get("due_date")) and today <= str(t.get("execution_date") or t.get("due_date"))[:10] < tomorrow
        and (t.get("status") or "") not in ("готово", "отменена")
    ]
    pay_sum = 0.0
    db = await _get_db()
    try:
        cur = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM payments
               WHERE status NOT IN ('оплачено', 'возврат')"""
        )
        pay_sum = float((await cur.fetchone())[0] or 0)
    finally:
        await db.close()
    pri = [t for t in due_today if (t.get("priority") or "") in ("критично", "высокий")]
    due_lines = [f"  • {(t.get('title') or '')[:80]}" for t in due_today[:12]]
    if not due_lines:
        due_lines = ["  —"]
    pri_lines = [f"  • {(t.get('title') or '')[:80]}" for t in pri[:8]]
    if not pri_lines:
        pri_lines = ["  —"]
    lines = [
        f"📅 {today}",
        f"🔴 Просрочено задач: {len(overdue)}",
        "⏰ Дедлайны сегодня:",
        *due_lines,
        f"💰 Ожидается оплат (сумма): {pay_sum:,.0f} ₽".replace(",", " "),
        "✅ Приоритетные сегодня:",
        *pri_lines,
    ]
    return "\n".join(lines)


async def build_hq_operating_context_block() -> str:
    """Краткий срез для промпта агентов (текст)."""
    try:
        bm = await get_business_metrics()
        kpi = {
            "active_clients": bm.get("active_clients"),
            "active_students": bm.get("active_students"),
            "total_paid": bm.get("total_paid"),
            "pending_payments": bm.get("pending_payments"),
            "open_tasks": bm.get("open_tasks"),
        }
        dl = await get_deadlines(14)
        soon = []
        for d in dl[:8]:
            due = d.get("deadline") or d.get("due_date")
            soon.append(
                f"- {(d.get('name') or d.get('title') or '?')[:80]} до {due}"
            )
        recent = await get_tasks(limit=5, offset=0)
        rt = []
        for t in recent:
            rt.append(f"- #{t.get('id')} {str(t.get('owner_message', ''))[:100]}")
        lines = [
            "=== СРЕЗ HQ (авто) ===",
            f"Активных клиентов: {kpi['active_clients']}, учеников: {kpi['active_students']}.",
            f"Оплачено всего: {kpi['total_paid']}, ожидается: {kpi['pending_payments']}.",
            f"Открытых задач по проектам (project_tasks): {kpi['open_tasks']}.",
            "Ближайшие дедлайны:",
            *(soon or ["- (нет в горизонте 14 дней)"]),
            "Последние задачи команды (orchestrator):",
            *(rt or ["- (нет)"]),
            "=== КОНЕЦ СРЕЗА ===",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("build_hq_operating_context_block: %s", e)
        return "=== СРЕЗ HQ: недоступен ==="


# ─────────────────────────────────────────────────────────────────────────────
# SEED: владелец и шаблоны проектов
# ─────────────────────────────────────────────────────────────────────────────

import hashlib as _hashlib


async def _seed_owner_user() -> None:
    """Создать пользователя-owner из ADMIN_PASSWORD при первом запуске.

    Идемпотентно: если запись с role=owner уже есть — ничего не делает.
    """
    pwd = os.getenv("ADMIN_PASSWORD", "Admin2024")
    if not pwd:
        return
    pwd_hash = _hashlib.sha256(pwd.encode("utf-8")).hexdigest()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute("SELECT id FROM hq_users WHERE role='owner' LIMIT 1")
        existing = await cur.fetchone()
        if existing:
            # Owner есть — обновим только хеш пароля (если пароль в .env поменяли).
            await db.execute(
                "UPDATE hq_users SET password_hash=? WHERE id=?",
                (pwd_hash, existing[0]),
            )
            await db.commit()
            return
        await db.execute(
            "INSERT INTO hq_users (name, login, password_hash, role, status) "
            "VALUES (?, ?, ?, 'owner', 'active')",
            ("Никита", "owner", pwd_hash),
        )
        await db.commit()
        logger.info("Создан пользователь-owner: login=owner")


async def _seed_delivery_templates() -> None:
    """Загрузить шаблоны проектов: при первом запуске или при обновлении до полного набора (8)."""
    if not FULL_DELIVERY_TEMPLATES:
        logger.warning("delivery_template_seed недоступен — шаблоны не загружены")
        return
    expected = len(FULL_DELIVERY_TEMPLATES)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute("SELECT COUNT(*) FROM delivery_templates")
        count = (await cur.fetchone())[0]
        if count >= expected:
            return
        if count > 0:
            await db.execute("DELETE FROM delivery_templates")
        for tmpl in FULL_DELIVERY_TEMPLATES:
            await db.execute(
                """INSERT INTO delivery_templates
                   (name, type, icon, estimated_days, description, stages_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    tmpl["name"],
                    tmpl["type"],
                    tmpl.get("icon", "📋"),
                    int(tmpl.get("estimated_days", 14)),
                    tmpl.get("description", ""),
                    json.dumps(tmpl["stages"], ensure_ascii=False),
                ),
            )
        await db.commit()
        logger.info("Seeded %d project templates", expected)
