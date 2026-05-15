"""
Базовый класс для всех AI-агентов.
Обеспечивает взаимодействие с Claude API, логирование в БД и делегирование.
"""

import os
import time
import logging
from dataclasses import dataclass, field

import anthropic
from pydantic import BaseModel

from agency_context_loader import get_agency_context
from agents.request_context import telegram_llm_mode, panel_model_override

logger = logging.getLogger("agents")

TELEGRAM_MAX_TOKENS = 4000

AGENCY_FOOTER = """

ВАЖНО ДЛЯ ВСЕХ ОТВЕТОВ:
- Отвечай без markdown форматирования (без ##, **, ---)
- Используй только текст и эмодзи для структуры
- Никаких вводных "Конечно!", "Отличный вопрос!"
- Начинай сразу с сути
- Если не знаешь — скажи прямо
"""


class AgentResponse(BaseModel):
    """Результат работы агента."""
    text: str
    tokens: int = 0
    success: bool = True
    error: str | None = None
    agent_name: str = ""
    role: str = ""


class AgentBase:
    """
    Базовый класс AI-агента. Каждый агент:
    - имеет имя, роль, отдел и руководителя
    - обращается к Claude API со своим system prompt
    - логирует каждое выполнение в БД
    - может делегировать задачи подчинённым агентам
    """

    def __init__(
        self,
        name: str,
        role: str,
        department: str,
        reports_to: str | None = None,
        max_tokens: int = 800,
    ):
        self.name = name
        self.role = role
        self.department = department
        self.reports_to = reports_to
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self._default_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    def _effective_model(self) -> str:
        override = panel_model_override.get()
        if override:
            return override
        return self._default_model

    @property
    def agency_context(self) -> str:
        """Динамически загружаемый контекст агентства для system prompt."""
        return get_agency_context()

    def build_system_prompt(self) -> str:
        """
        Собирает полный system prompt агента.
        Переопределяется в подклассах для добавления специфичных инструкций.
        """
        return (
            f"Ты — {self.role} в агентстве AI Delivery.\n"
            f"Твоё имя в системе: {self.name}\n"
            f"Отдел: {self.department}\n"
            f"Подчиняешься: {self.reports_to or 'владельцу'}\n\n"
            f"{self.agency_context}\n\n"
            "Отвечай всегда на русском языке.\n"
            "Будь конкретен. Давай actionable результаты.\n"
            "Не используй запрещённые слова из контекста агентства."
        )

    async def think(
        self,
        task_input: str,
        context: dict | None = None,
        task_id: int | None = None,
        max_tokens: int | None = None,
        log_execution: bool = True,
    ) -> AgentResponse:
        """
        Основной метод: отправить задачу в Claude и получить ответ.
        Логирует выполнение в БД (если log_execution и передан task_id).
        """
        from database import add_execution, build_hq_operating_context_block

        system_prompt = self.build_system_prompt() + AGENCY_FOOTER

        try:
            hq_snap = await build_hq_operating_context_block()
        except Exception:
            hq_snap = ""
        user_message = task_input
        if hq_snap:
            user_message = f"{hq_snap}\n\n{user_message}"
        if context:
            context_lines = "\n".join(
                f"[{k}]: {v}" for k, v in context.items()
            )
            user_message = f"{task_input}\n\nДополнительный контекст:\n{context_lines}"

        if max_tokens is not None:
            effective_max = max_tokens
        elif telegram_llm_mode.get():
            effective_max = TELEGRAM_MAX_TOKENS
        else:
            effective_max = self._max_tokens

        start = time.time()
        try:
            response = await self._client.messages.create(
                model=self._effective_model(),
                max_tokens=effective_max,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            text = response.content[0].text
            tokens = response.usage.input_tokens + response.usage.output_tokens

            result = AgentResponse(
                text=text,
                tokens=tokens,
                success=True,
                agent_name=self.name,
                role=self.role,
            )

            if log_execution and task_id:
                await add_execution(
                    task_id=task_id,
                    agent_name=self.name,
                    agent_role=self.role,
                    input_brief=task_input[:2000],
                    output_text=text[:5000],
                    tokens=tokens,
                    parent_agent=self.reports_to,
                    status="done",
                )

            logger.info(
                "[%s] выполнил задачу. Токены: %d. Время: %.1fс",
                self.name, tokens, time.time() - start,
            )
            return result

        except Exception as e:
            error_msg = f"Ошибка агента {self.name}: {str(e)}"
            logger.error(error_msg, exc_info=True)

            if log_execution and task_id:
                await add_execution(
                    task_id=task_id,
                    agent_name=self.name,
                    agent_role=self.role,
                    input_brief=task_input[:2000],
                    output_text=None,
                    tokens=0,
                    parent_agent=self.reports_to,
                    status="error",
                )

            return AgentResponse(
                text="",
                tokens=0,
                success=False,
                error=error_msg,
                agent_name=self.name,
                role=self.role,
            )

    async def delegate(
        self,
        agent: "AgentBase",
        brief: str,
        task_id: int,
        context: dict | None = None,
    ) -> AgentResponse:
        """
        Делегировать задачу другому агенту (подчинённому).
        Логирует цепочку: кто кому делегировал.
        """
        logger.info(
            "[%s] делегирует задачу → [%s]: %s",
            self.name, agent.name, brief[:100],
        )
        delegation_context = context or {}
        delegation_context["delegated_by"] = f"{self.name} ({self.role})"

        return await agent.think(
            task_input=brief,
            context=delegation_context,
            task_id=task_id,
        )
