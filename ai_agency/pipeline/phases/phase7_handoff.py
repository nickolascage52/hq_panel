"""Phase 7 — Handoff (T-4-004, Sprint 4).

Generates docs/final-report.md, runs deploy strategy, updates
delivery_projects.status to 'На проверке', emits handoff_complete event.
Telegram notification is wired separately in T-4-010 (telegram bot watcher
that subscribes to handoff_complete events).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import aiosqlite

from database import DB_PATH

from ..deploy import deploy
from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase7Handoff(PhaseBase):
    name = 'handoff'

    async def _run(self) -> None:
        run = self.runner.run_data
        run_id = self.runner.run_id

        await self._write_final_report(run)

        production_url: str | None = None
        if os.getenv('PIPELINE_FORCE_STUB') != 'true':
            production_url = await deploy(
                run.get('deploy_strategy', 'none'),
                str(self.runner.workspace.path),
                run_id,
            )
        else:
            await asyncio.sleep(0.5)

        async with aiosqlite.connect(str(DB_PATH)) as db:
            if production_url:
                await db.execute(
                    'UPDATE pipeline_runs SET github_repo_url = COALESCE(github_repo_url, ?) WHERE id = ?',
                    (production_url, run_id),
                )
            dp_id = run.get('delivery_project_id')
            if dp_id:
                await db.execute(
                    'UPDATE delivery_projects SET status = ?, production_url = COALESCE(production_url, ?) WHERE id = ?',
                    ('На проверке', production_url, dp_id),
                )
            await db.commit()

        await self.runner.progress.emit_event(
            'handoff_complete',
            payload={
                'production_url': production_url,
                'delivery_project_id': run.get('delivery_project_id'),
                'workspace_path': str(self.runner.workspace.path),
            },
        )
        logger.info('Phase7: handoff complete for run %s (url=%s)', run_id, production_url)

    async def _write_final_report(self, run: dict) -> None:
        ws = self.runner.workspace.path
        report_path = ws / 'docs' / 'final-report.md'
        report_path.parent.mkdir(parents=True, exist_ok=True)

        files_in_docs = sorted([p.name for p in (ws / 'docs').glob('*.md')]) if (ws / 'docs').exists() else []
        sprints = sorted([p.name for p in (ws / 'docs' / 'sprints').glob('*.md')]) if (ws / 'docs' / 'sprints').exists() else []

        lines = [
            f'# Final Report — Pipeline Run #{self.runner.run_id}',
            '',
            f'**Title:** {run.get("title", "")}',
            f'**Project type:** {run.get("project_type", "")}',
            f'**Autonomy level:** {run.get("autonomy_level", "")}',
            f'**Deploy strategy:** {run.get("deploy_strategy", "")}',
            f'**Generated:** {datetime.now().isoformat(sep=" ", timespec="seconds")}',
            '',
            '## Workspace deliverables',
            '',
            '### docs/',
        ]
        if files_in_docs:
            lines.extend(f'- {f}' for f in files_in_docs)
        else:
            lines.append('_(empty)_')
        lines.extend(['', '### docs/sprints/'])
        if sprints:
            lines.extend(f'- {f}' for f in sprints)
        else:
            lines.append('_(no sprint files)_')
        lines.extend([
            '',
            '## Next steps',
            '',
            '1. Owner reviews the workspace.',
            '2. If approved, merge pipeline branch into main project repo.',
            '3. delivery_projects.status updated to "На проверке".',
        ])
        report_path.write_text('\n'.join(lines), encoding='utf-8')
        logger.info('Phase7: wrote final-report.md (%d lines)', len(lines))
