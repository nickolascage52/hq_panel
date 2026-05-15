"""Wrapper around claude-agent-sdk for spawning agent personas.

Implemented in Sprint 3 (T-3-XXX). Currently a stub.
"""
import logging
logger = logging.getLogger(__name__)


async def run_phase_agent(
    workspace_path: str,
    agent_persona: str,
    task_md: str,
    model: str = 'opus',
    timeout: int = 1800,
):
    raise NotImplementedError('Implemented in Sprint 3')
