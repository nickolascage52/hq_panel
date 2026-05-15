-- Pipeline Module — Database Schema Seed
-- Target: ai_agency/agency.db (existing)
-- All migrations are idempotent — safe to run multiple times.
-- These are added in ai_agency/database.py:init_db() via _add_pipeline_tables(db).

-- ============================================================
-- Sprint 1: hq_sessions (replaces in-memory _sessions dict)
-- ============================================================

CREATE TABLE IF NOT EXISTS hq_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES hq_users(id),
    role TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_hq_sessions_token ON hq_sessions(token);
CREATE INDEX IF NOT EXISTS idx_hq_sessions_expires ON hq_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_hq_sessions_user ON hq_sessions(user_id);


-- ============================================================
-- Sprint 2: pipeline_* tables
-- ============================================================

-- Main entity: one row per pipeline-run
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Optional link to existing delivery_project (FK exists once delivery tables loaded)
    delivery_project_id INTEGER REFERENCES delivery_projects(id),

    title TEXT NOT NULL,
    raw_idea TEXT NOT NULL,               -- what user originally typed
    production_prompt TEXT,                -- after /prompt-forge

    project_type TEXT NOT NULL,            -- landing | telegram_bot | n8n | ai_assistant | custom
    autonomy_level INTEGER NOT NULL DEFAULT 2,  -- 1, 2, or 3
    deploy_strategy TEXT NOT NULL DEFAULT 'none', -- none | vercel | aeza | custom

    status TEXT NOT NULL DEFAULT 'pending',
    -- pending | running | paused_user | paused_rate_limit | awaiting_approval
    -- | validating | deploying | review | done | failed | aborted

    current_phase TEXT,                    -- prompt|prd|architecture|sprints|execution|validation|handoff
    current_sprint_id INTEGER,             -- FK pipeline_sprints (created Phase 4+)

    workspace_path TEXT,                   -- /var/www/.../pipeline_workspaces/<id>/
    tmux_session_name TEXT,                -- pipeline-run-<id>
    git_branch TEXT,                       -- pipeline/<id>-<slug>
    github_repo_url TEXT,                  -- if pushed to GitHub

    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    pause_reason TEXT,
    resume_after TIMESTAMP,                -- for auto-resume (rate limit)
    completed_at TIMESTAMP,

    initiated_by INTEGER REFERENCES hq_users(id),
    error_message TEXT,                    -- if failed

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_delivery_project ON pipeline_runs(delivery_project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_resume_after ON pipeline_runs(resume_after) WHERE resume_after IS NOT NULL;


-- Sprints within a pipeline-run (created during Phase 4)
CREATE TABLE IF NOT EXISTS pipeline_sprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,

    -- Mirror in delivery_stages for HQ UI compatibility
    delivery_stage_id INTEGER REFERENCES delivery_stages(id),

    sprint_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    goal TEXT,
    spec_md TEXT,                          -- full content of sprint-N.md

    status TEXT NOT NULL DEFAULT 'planned',
    -- planned | active | validating | done | failed

    tasks_total INTEGER DEFAULT 0,
    tasks_done INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, sprint_number)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_sprints_run ON pipeline_sprints(run_id);


-- Event log: everything that happens in a pipeline-run
CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    sprint_id INTEGER REFERENCES pipeline_sprints(id),
    delivery_task_id INTEGER REFERENCES delivery_tasks(id),

    event_type TEXT NOT NULL,
    -- phase_started | phase_completed | task_started | task_done | task_failed
    -- | commit | pr_created | rate_limit_hit | model_downgraded | paused
    -- | resumed | approval_needed | user_directive | telegram_sent | error
    -- | preview_deployed | handoff_complete

    severity TEXT DEFAULT 'info',           -- info | warning | error
    payload_json TEXT,                      -- JSON details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_run ON pipeline_events(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_type ON pipeline_events(event_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_sprint ON pipeline_events(sprint_id) WHERE sprint_id IS NOT NULL;


-- Chat with pipeline (per-run conversation, including user directives)
CREATE TABLE IF NOT EXISTS pipeline_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                     -- user | orchestrator | agent_result | system
    agent_name TEXT,                        -- for role='agent_result' (e.g. 'architect')
    content_md TEXT NOT NULL,
    metadata_json TEXT,                     -- tools called, tokens used, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_chat_run ON pipeline_chat_messages(run_id, created_at);


-- Rate limit state (3 rows: opus, sonnet, haiku — seeded on init)
CREATE TABLE IF NOT EXISTS pipeline_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL UNIQUE,             -- 'opus' | 'sonnet' | 'haiku'
    tokens_used_weekly INTEGER DEFAULT 0,
    tokens_limit_weekly INTEGER,
    weekly_reset_at TIMESTAMP,
    tokens_used_session INTEGER DEFAULT 0,
    session_reset_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed: 3 rows for known models (idempotent via INSERT OR IGNORE)
INSERT OR IGNORE INTO pipeline_rate_limits (model) VALUES ('opus');
INSERT OR IGNORE INTO pipeline_rate_limits (model) VALUES ('sonnet');
INSERT OR IGNORE INTO pipeline_rate_limits (model) VALUES ('haiku');


-- ============================================================
-- WAL mode (Sprint 2)
-- ============================================================
-- Note: PRAGMA statements run at connection setup, not as table definitions.
-- Add to database.py connection setup:
--   await db.execute('PRAGMA journal_mode=WAL')
--   await db.execute('PRAGMA synchronous=NORMAL')
