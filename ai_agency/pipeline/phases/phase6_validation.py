"""Phase 6 — Final validation (T-4-003, Sprint 4).

Sprint 4 v1.0 stub: inspects workspace for project markers (package.json,
pyproject.toml, requirements.txt) and emits an inspection event. Real
implementation (subprocess npm run build, pytest, etc.) deferred to backlog
v1.1 — needs decision on which stack to support first and how to surface
build errors back into pipeline_events.
"""
from __future__ import annotations

import asyncio
import logging
import os

from .base import PhaseBase

logger = logging.getLogger(__name__)


class Phase6Validation(PhaseBase):
    name = 'validation'

    async def _run(self) -> None:
        ws = self.runner.workspace.path
        has_npm = (ws / 'package.json').exists()
        has_py = (ws / 'pyproject.toml').exists() or (ws / 'requirements.txt').exists()

        await self.runner.progress.emit_event(
            'validation_inspection',
            payload={'has_package_json': has_npm, 'has_python_project': has_py},
        )

        sleep_t = 0.5 if os.getenv('PIPELINE_FORCE_STUB') == 'true' else 1.5
        await asyncio.sleep(sleep_t)

        logger.info('Phase6: validation stub complete (npm=%s, py=%s)', has_npm, has_py)
