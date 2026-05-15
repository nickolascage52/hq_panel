"""Pipeline deploy strategies (T-4-005, Sprint 4).

Implementations:
- 'none'   — no-op, returns None URL (default for v1)
- 'vercel' — stub: requires VERCEL_TOKEN, runs `vercel deploy`
- 'aeza'   — stub: rsync to /var/www/preview/<run_id>/, returns nginx subdomain URL
- 'custom' — owner edits this module to add their own

Each strategy returns the production_url (or None) which Phase 7 stores in
pipeline_runs and delivery_projects.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


async def deploy(strategy: str, workspace_path: str, run_id: int) -> str | None:
    """Dispatch to the right strategy. Returns production_url or None."""
    handlers = {
        'none':   _deploy_none,
        'vercel': _deploy_vercel,
        'aeza':   _deploy_aeza,
        'custom': _deploy_custom,
    }
    fn = handlers.get(strategy, _deploy_none)
    return await fn(workspace_path, run_id)


async def _deploy_none(workspace_path: str, run_id: int) -> None:
    logger.info('Deploy: strategy=none for run %s — no URL', run_id)
    return None


async def _deploy_vercel(workspace_path: str, run_id: int) -> str | None:
    token = os.getenv('VERCEL_TOKEN')
    if not token:
        logger.warning('Deploy(vercel): VERCEL_TOKEN missing — skipping deploy for run %s', run_id)
        return None
    # Stub for Sprint 4 — real implementation runs subprocess to `vercel`.
    logger.info('Deploy(vercel): stub — real implementation in v1.1 backlog')
    return None


async def _deploy_aeza(workspace_path: str, run_id: int) -> str | None:
    # Stub: rsync to preview server. Real implementation needs:
    # - SSH key on this host with access to deploy target
    # - nginx config for preview-{N}.hq.ai-delivery.shop subdomain
    logger.info('Deploy(aeza): stub — real implementation in v1.1 backlog')
    return None


async def _deploy_custom(workspace_path: str, run_id: int) -> str | None:
    logger.info('Deploy(custom): no implementation provided')
    return None
