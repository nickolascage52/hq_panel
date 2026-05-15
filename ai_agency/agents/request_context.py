"""Контекст запроса: повышенный лимит токенов для Telegram и др."""

from contextvars import ContextVar

# True — вызов LLM из Telegram-бота (max_tokens 4000 в AgentBase.think).
telegram_llm_mode: ContextVar[bool] = ContextVar("telegram_llm_mode", default=False)

# Если задан — AgentBase использует эту модель вместо CLAUDE_MODEL (HQ / сохранённые настройки).
panel_model_override: ContextVar[str | None] = ContextVar(
    "panel_model_override", default=None
)
