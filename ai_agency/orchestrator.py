"""
Асинхронный оркестратор задач.
Управляет потоком выполнения: владелец → Chief of Staff → отделы → специалисты → отчёт.
"""

import asyncio
import json
import os
import time
import logging
from datetime import datetime, date
from typing import Any

from pydantic import BaseModel

from database import (
    create_task, update_task, get_task_chain, save_content,
    update_content_status, get_metrics, save_report, get_task,
    get_content_for_task,
)
from agents.base import AgentResponse
from agents.team import AgencyTeam
from agents.context import client_solutions_trigger_keywords

logger = logging.getLogger("orchestrator")


class AgentExecution(BaseModel):
    agent_name: str
    role: str
    input_brief: str
    output_text: str
    tokens: int
    success: bool


class OrchestratorResult(BaseModel):
    task_id: int
    success: bool
    final_report: str
    chain: list[AgentExecution]
    content_ids: list[int]
    duration_seconds: float


class TaskProgress:
    """Трекер прогресса задачи для WebSocket стриминга."""

    def __init__(self, task_id: int):
        self.task_id = task_id
        self.steps: list[dict] = []
        self._listeners: list[asyncio.Queue] = []

    def add_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def remove_listener(self, q: asyncio.Queue):
        if q in self._listeners:
            self._listeners.remove(q)

    async def emit(self, step: dict):
        self.steps.append(step)
        for q in self._listeners:
            await q.put(step)

    async def complete(self):
        for q in self._listeners:
            await q.put(None)


class Orchestrator:
    """
    Главный оркестратор. Принимает задачи, распределяет по агентам,
    собирает результаты и формирует отчёт для владельца.
    """

    def __init__(self):
        self.team = AgencyTeam()
        self._active_tasks: dict[int, TaskProgress] = {}

    def get_progress(self, task_id: int) -> TaskProgress | None:
        return self._active_tasks.get(task_id)

    async def run_task(
        self,
        owner_message: str,
        task_id: int | None = None,
        task_mode: str | None = None,
    ) -> OrchestratorResult:
        """
        Главный метод. Принимает сообщение от владельца и прогоняет
        через иерархию агентов. Режим: lite / standard / full (Chief + опционально task_mode с API).
        """
        start_time = time.time()
        chain: list[AgentExecution] = []
        content_ids: list[int] = []

        if task_id is None:
            task_id = await create_task(owner_message)

        progress = TaskProgress(task_id)
        self._active_tasks[task_id] = progress

        try:
            await update_task(task_id, status="running")
            await progress.emit({
                "stage": "start",
                "agent": "system",
                "message": f"Задача #{task_id} принята.",
            })

            if self._should_route_client_solutions(owner_message):
                await progress.emit({
                    "stage": "client_solutions",
                    "agent": "system",
                    "message": "Маршрут: отдел AI Solutions (анализ клиента).",
                })
                return await self.run_client_analysis(
                    owner_message,
                    task_id=task_id,
                    task_mode=task_mode,
                    progress=progress,
                )

            await progress.emit({
                "stage": "start",
                "agent": "system",
                "message": f"Передаю Chief of Staff.",
            })

            # ── Шаг 1: Chief of Staff анализирует задачу ──
            await progress.emit({
                "stage": "analysis",
                "agent": "chief_of_staff",
                "message": "Chief of Staff анализирует задачу...",
            })

            chief_analysis = await self.team.chief.think(
                task_input=(
                    f"Владелец агентства поставил задачу:\n\n{owner_message}\n\n"
                    "Оцени сложность и выбери режим выполнения:\n"
                    "- lite: один простой результат (например один пост в Telegram) — только Chief + один "
                    "профильный агент, без руководителя отдела.\n"
                    "- standard: углублённая работа (анализ конкурента, серия материалов) — Chief + "
                    "руководитель отдела + 1–2 специалиста на отдел.\n"
                    "- full: комплекс (аудит сайта, несколько направлений) — полная цепочка отдела.\n\n"
                    "Правила: простой пост в Telegram → lite; анализ конкурента → standard; полный аудит "
                    "сайта / несколько отделов → full.\n\n"
                    "Проанализируй задачу и определи:\n"
                    "1. Какие отделы нужно задействовать\n"
                    "2. Что конкретно должен сделать каждый отдел\n"
                    "3. task_mode: lite | standard | full\n"
                    "4. Для lite обязательно укажи primary_agent (имя из реестра: telegram_writer, "
                    "threads_writer, market_analyst, competitor_analyst, trend_analyst, offer_strategist, "
                    "hypothesis_analyst, cro_analyst, web_copywriter, vc_writer) и при необходимости "
                    "primary_brief.\n\n"
                    "Ответь в формате JSON:\n"
                    "{\n"
                    '  "summary": "краткое описание задачи",\n'
                    '  "task_mode": "lite" | "standard" | "full",\n'
                    '  "primary_agent": "имя агента или пустая строка если не lite",\n'
                    '  "primary_brief": "бриф для lite-агента или пустая строка",\n'
                    '  "departments": {\n'
                    '    "content": {"needed": true/false, "brief": "задание для контент-отдела"},\n'
                    '    "research": {"needed": true/false, "brief": "задание для аналитики"},\n'
                    '    "product": {"needed": true/false, "brief": "задание для продукт-отдела"},\n'
                    '    "website": {"needed": true/false, "brief": "задание для сайт-отдела"}\n'
                    "  }\n"
                    "}\n\n"
                    "Если задача не подходит ни к одному отделу — поставь needed: false везде и кратко "
                    "опиши в summary; task_mode может быть lite.\n\n"
                    "Важно: если запрос про ситуацию клиента, подбор ИИ-решения, КП или внедрение у клиента — "
                    "система уже могла направить задачу в пайплайн AI Solutions до этого шага; тогда этот JSON "
                    "может быть неиспользован.\n\n"
                    "После выполнения задачи (в финальном отчёте владельцу):\n"
                    "1. Если задача сложная — предложи план.\n"
                    "2. Укажи, каких агентов имеет смысл подключить дальше.\n"
                    "3. В конце предложи 1–2 идеи для развития агентства только если это уместно по контексту.\n"
                    "4. Спроси: «Превратить идею в задачу?»"
                ),
                task_id=task_id,
            )

            chain.append(AgentExecution(
                agent_name="chief_of_staff",
                role="Chief of Staff",
                input_brief=owner_message[:500],
                output_text=chief_analysis.text[:2000],
                tokens=chief_analysis.tokens,
                success=chief_analysis.success,
            ))

            if not chief_analysis.success:
                await update_task(
                    task_id, status="error",
                    error=chief_analysis.error,
                    duration=time.time() - start_time,
                )
                return OrchestratorResult(
                    task_id=task_id,
                    success=False,
                    final_report=f"Ошибка Chief of Staff: {chief_analysis.error}",
                    chain=chain,
                    content_ids=[],
                    duration_seconds=time.time() - start_time,
                )

            # ── Шаг 2: Парсим план и запускаем отделы ──
            plan = self._parse_chief_plan(chief_analysis.text)
            department_results: dict[str, str] = {}

            tasks_to_run = []
            for dept_key in ("content", "research", "product", "website"):
                d = plan.get(dept_key)
                if isinstance(d, dict) and d.get("needed"):
                    tasks_to_run.append((dept_key, d.get("brief", owner_message)))

            effective_mode = self._resolve_task_mode(plan.get("task_mode"), task_mode)

            await progress.emit({
                "stage": "mode",
                "agent": "chief_of_staff",
                "message": f"Режим выполнения: {effective_mode}",
            })

            ran_lite = False
            if effective_mode == "lite" and tasks_to_run:
                dept_name, brief = tasks_to_run[0]
                agent_name = (plan.get("primary_agent") or "").strip() or self._infer_lite_agent(dept_name)
                agent = self.team.get(agent_name)
                if agent is None:
                    logger.warning(
                        "Режим lite: агент %s не найден, переключаюсь на standard",
                        agent_name,
                    )
                    effective_mode = "standard"
                else:
                    ran_lite = True
                    brief_text = (plan.get("primary_brief") or brief or owner_message).strip()
                    await progress.emit({
                        "stage": "lite",
                        "agent": agent_name,
                        "message": f"Lite: один агент — {agent_name}",
                    })
                    lite_resp = await agent.think(brief_text, task_id=task_id)
                    chain.append(AgentExecution(
                        agent_name=agent_name,
                        role=getattr(agent, "role", agent_name),
                        input_brief=brief_text[:500],
                        output_text=lite_resp.text[:2000],
                        tokens=lite_resp.tokens,
                        success=lite_resp.success,
                    ))
                    department_results["lite"] = (
                        lite_resp.text if lite_resp.success else f"Ошибка: {lite_resp.error}"
                    )

            if not ran_lite:
                if not tasks_to_run:
                    department_results["chief_direct"] = chief_analysis.text
                else:
                    async def run_department(dept_name: str, brief: str):
                        await progress.emit({
                            "stage": "department",
                            "agent": dept_name,
                            "message": f"Отдел {dept_name} начал работу ({effective_mode})...",
                        })
                        result = await self._run_department(
                            dept_name,
                            brief,
                            task_id,
                            chain,
                            content_ids,
                            progress,
                            run_mode=effective_mode,
                        )
                        department_results[dept_name] = result

                    await asyncio.gather(
                        *[run_department(name, br) for name, br in tasks_to_run]
                    )

            # ── Шаг 4: Chief of Staff формирует итоговый отчёт ──
            await progress.emit({
                "stage": "report",
                "agent": "chief_of_staff",
                "message": "Chief of Staff формирует итоговый отчёт...",
            })

            results_summary = "\n\n".join(
                f"=== Результат от отдела {dept} ===\n{text[:3000]}"
                for dept, text in department_results.items()
            )

            final_report_response = await self.team.chief.think(
                task_input=(
                    f"Задача владельца: {owner_message}\n\n"
                    f"Результаты от отделов:\n\n{results_summary}\n\n"
                    "Сформируй итоговый структурированный отчёт для владельца. "
                    "Включи: что было сделано, ключевые результаты, рекомендации. "
                    "Если есть готовый контент — укажи его статус."
                ),
                task_id=task_id,
            )

            chain.append(AgentExecution(
                agent_name="chief_of_staff",
                role="Chief of Staff (итоговый отчёт)",
                input_brief="Формирование отчёта владельцу",
                output_text=final_report_response.text[:3000],
                tokens=final_report_response.tokens,
                success=final_report_response.success,
            ))

            duration = time.time() - start_time
            final_text = final_report_response.text if final_report_response.success else (
                f"Ошибка формирования отчёта: {final_report_response.error}\n\n"
                f"Сырые результаты:\n{results_summary[:3000]}"
            )

            await update_task(
                task_id,
                status="done",
                result=final_text[:5000],
                duration=duration,
            )

            await progress.emit({
                "stage": "done",
                "agent": "system",
                "message": f"Задача #{task_id} выполнена за {duration:.1f}с",
            })
            await progress.complete()

            return OrchestratorResult(
                task_id=task_id,
                success=True,
                final_report=final_text,
                chain=chain,
                content_ids=content_ids,
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error("Ошибка оркестратора задачи #%d: %s", task_id, e, exc_info=True)
            duration = time.time() - start_time
            await update_task(
                task_id, status="error",
                error=str(e),
                duration=duration,
            )
            await progress.emit({
                "stage": "error",
                "agent": "system",
                "message": f"Ошибка: {str(e)}",
            })
            await progress.complete()
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report=f"Ошибка выполнения: {str(e)}",
                chain=chain,
                content_ids=[],
                duration_seconds=duration,
            )
        finally:
            self._active_tasks.pop(task_id, None)

    async def _run_department(
        self,
        dept_name: str,
        brief: str,
        task_id: int,
        chain: list[AgentExecution],
        content_ids: list[int],
        progress: TaskProgress,
        run_mode: str = "full",
    ) -> str:
        """Запустить отдел: руководитель → специалисты → QA (для контента, только full)."""

        if dept_name == "content":
            return await self._run_content_department(
                brief, task_id, chain, content_ids, progress, run_mode=run_mode,
            )
        elif dept_name == "research":
            return await self._run_research_department(
                brief, task_id, chain, progress, run_mode=run_mode,
            )
        elif dept_name == "product":
            return await self._run_product_department(
                brief, task_id, chain, progress, run_mode=run_mode,
            )
        elif dept_name == "website":
            return await self._run_website_department(
                brief, task_id, chain, progress, run_mode=run_mode,
            )
        else:
            return f"Неизвестный отдел: {dept_name}"

    async def _run_content_department(
        self,
        brief: str,
        task_id: int,
        chain: list[AgentExecution],
        content_ids: list[int],
        progress: TaskProgress,
        run_mode: str = "full",
    ) -> str:
        """Контент-отдел: директор → копирайтеры → QA (QA только full)."""

        director_response = await self.team.chief.delegate(
            self.team.content_director,
            brief=f"Задание от Chief of Staff:\n{brief}\n\nОпредели какой контент нужно создать и дай задания копирайтерам.",
            task_id=task_id,
        )
        chain.append(AgentExecution(
            agent_name="content_director", role="Контент-директор",
            input_brief=brief[:500], output_text=director_response.text[:2000],
            tokens=director_response.tokens, success=director_response.success,
        ))

        if not director_response.success:
            return f"Ошибка контент-директора: {director_response.error}"

        writer_results = []

        writer_jobs = [
            (
                "telegram_writer",
                self.team.telegram_writer,
                "Telegram-копирайтер пишет пост...",
                "Написать Telegram-пост",
                "telegram",
                "Напиши пост для Telegram.",
            ),
        ]
        if run_mode == "full":
            writer_jobs.append(
                (
                    "threads_writer",
                    self.team.threads_writer,
                    "Threads-копирайтер пишет пост...",
                    "Написать Threads-пост",
                    "threads",
                    "Напиши пост для Threads.",
                ),
            )

        for wname, writer_agent, prog_msg, input_label, channel, instr in writer_jobs:
            await progress.emit({"stage": "specialist", "agent": wname, "message": prog_msg})
            resp = await self.team.content_director.delegate(
                writer_agent,
                brief=(
                    f"Задание от контент-директора:\n{director_response.text[:2000]}\n\n{instr}"
                ),
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name=wname,
                role=writer_agent.role,
                input_brief=input_label,
                output_text=resp.text[:2000],
                tokens=resp.tokens,
                success=resp.success,
            ))
            if resp.success:
                writer_results.append((channel, resp.text))

        qa_results = []
        for channel, text in writer_results:
            if run_mode == "full":
                await progress.emit({
                    "stage": "qa",
                    "agent": "qa_editor",
                    "message": f"QA проверяет {channel}...",
                })
                qa_response = await self.team.qa_editor.qa_check(text, channel, task_id)
                chain.append(AgentExecution(
                    agent_name="qa_editor",
                    role="QA-редактор",
                    input_brief=f"QA-проверка {channel}",
                    output_text=qa_response.text[:2000],
                    tokens=qa_response.tokens,
                    success=qa_response.success,
                ))
                final_text = qa_response.text if qa_response.success else text
                qa_passed = qa_response.success and "ОДОБРЕНО" in qa_response.text.upper()
            else:
                final_text = text
                qa_passed = False

            content_id = await save_content(
                task_id=task_id,
                channel=channel,
                topic=brief[:200],
                body=final_text,
                rubric="auto",
            )
            content_ids.append(content_id)
            if qa_passed:
                await update_content_status(content_id, "approved")

            if run_mode == "full":
                qa_results.append(
                    f"[{channel}] контент #{content_id} — "
                    f"{'одобрен' if qa_passed else 'на проверке'}"
                )
            else:
                qa_results.append(
                    f"[{channel}] контент #{content_id} — черновик (standard, без QA)"
                )

        return (
            f"Контент-отдел завершил работу.\n"
            f"Создано единиц контента: {len(writer_results)}\n"
            + "\n".join(qa_results)
        )

    async def _run_research_department(
        self,
        brief: str,
        task_id: int,
        chain: list[AgentExecution],
        progress: TaskProgress,
        run_mode: str = "full",
    ) -> str:
        """Аналитический отдел: руководитель → аналитики (в standard — один аналитик)."""

        head_response = await self.team.chief.delegate(
            self.team.research_head,
            brief=f"Задание от Chief of Staff:\n{brief}\n\nОпредели какие исследования нужны и дай задания аналитикам.",
            task_id=task_id,
        )
        chain.append(AgentExecution(
            agent_name="research_head", role="Руководитель аналитики",
            input_brief=brief[:500], output_text=head_response.text[:2000],
            tokens=head_response.tokens, success=head_response.success,
        ))

        if not head_response.success:
            return f"Ошибка руководителя аналитики: {head_response.error}"

        analyst_results = []

        bl = brief.lower()
        if run_mode == "standard":
            if any(k in bl for k in ("конкурент", "competitor", "конкурентов")):
                analyst_specs = [
                    (self.team.competitor_analyst, "competitor_analyst", "Аналитик конкурентов"),
                ]
            elif "тренд" in bl:
                analyst_specs = [
                    (self.team.trend_analyst, "trend_analyst", "Трендовый аналитик"),
                ]
            else:
                analyst_specs = [
                    (self.team.market_analyst, "market_analyst", "Рыночный аналитик"),
                ]
        else:
            analyst_specs = [
                (self.team.market_analyst, "market_analyst", "Рыночный аналитик"),
                (self.team.trend_analyst, "trend_analyst", "Трендовый аналитик"),
            ]

        async def run_analyst(agent, name, label):
            await progress.emit({"stage": "specialist", "agent": name, "message": f"{label} работает..."})
            resp = await self.team.research_head.delegate(
                agent,
                brief=f"Задание от руководителя аналитики:\n{head_response.text[:2000]}",
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name=name,
                role=label,
                input_brief=brief[:300],
                output_text=resp.text[:2000],
                tokens=resp.tokens,
                success=resp.success,
            ))
            if resp.success:
                analyst_results.append(f"=== {label} ===\n{resp.text[:2000]}")

        await asyncio.gather(
            *[run_analyst(a, n, lbl) for a, n, lbl in analyst_specs]
        )

        return f"Аналитический отдел завершил работу.\n\n" + "\n\n".join(analyst_results)

    async def _run_product_department(
        self,
        brief: str,
        task_id: int,
        chain: list[AgentExecution],
        progress: TaskProgress,
        run_mode: str = "full",
    ) -> str:
        """Продуктовый отдел: менеджер → специалисты (в standard — один специалист)."""

        pm_response = await self.team.chief.delegate(
            self.team.product_manager,
            brief=f"Задание от Chief of Staff:\n{brief}",
            task_id=task_id,
        )
        chain.append(AgentExecution(
            agent_name="product_manager", role="Продакт-менеджер",
            input_brief=brief[:500], output_text=pm_response.text[:2000],
            tokens=pm_response.tokens, success=pm_response.success,
        ))

        if not pm_response.success:
            return f"Ошибка продакт-менеджера: {pm_response.error}"

        specialist_results = []

        if run_mode == "standard":
            spec_list = [
                (self.team.offer_strategist, "offer_strategist", "Стратег по офферам"),
            ]
        else:
            spec_list = [
                (self.team.offer_strategist, "offer_strategist", "Стратег по офферам"),
                (self.team.hypothesis_analyst, "hypothesis_analyst", "Аналитик гипотез"),
            ]

        async def run_specialist(agent, name, label):
            await progress.emit({"stage": "specialist", "agent": name, "message": f"{label} работает..."})
            resp = await self.team.product_manager.delegate(
                agent,
                brief=f"Задание от продакт-менеджера:\n{pm_response.text[:2000]}",
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name=name,
                role=label,
                input_brief=brief[:300],
                output_text=resp.text[:2000],
                tokens=resp.tokens,
                success=resp.success,
            ))
            if resp.success:
                specialist_results.append(f"=== {label} ===\n{resp.text[:2000]}")

        await asyncio.gather(
            *[run_specialist(a, n, lbl) for a, n, lbl in spec_list]
        )

        return f"Продуктовый отдел завершил работу.\n\n" + "\n\n".join(specialist_results)

    async def _run_website_department(
        self,
        brief: str,
        task_id: int,
        chain: list[AgentExecution],
        progress: TaskProgress,
        run_mode: str = "full",
    ) -> str:
        """Отдел сайта: стратег → CRO + копирайтер (в standard — только CRO)."""

        ws_response = await self.team.chief.delegate(
            self.team.website_strategist,
            brief=f"Задание от Chief of Staff:\n{brief}",
            task_id=task_id,
        )
        chain.append(AgentExecution(
            agent_name="website_strategist", role="Стратег по сайту",
            input_brief=brief[:500], output_text=ws_response.text[:2000],
            tokens=ws_response.tokens, success=ws_response.success,
        ))

        if not ws_response.success:
            return f"Ошибка стратега по сайту: {ws_response.error}"

        specialist_results = []

        if run_mode == "standard":
            spec_list = [
                (self.team.cro_analyst, "cro_analyst", "CRO-аналитик"),
            ]
        else:
            spec_list = [
                (self.team.cro_analyst, "cro_analyst", "CRO-аналитик"),
                (self.team.web_copywriter, "web_copywriter", "Веб-копирайтер"),
            ]

        async def run_specialist(agent, name, label):
            await progress.emit({"stage": "specialist", "agent": name, "message": f"{label} работает..."})
            resp = await self.team.website_strategist.delegate(
                agent,
                brief=f"Задание от стратега по сайту:\n{ws_response.text[:2000]}",
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name=name,
                role=label,
                input_brief=brief[:300],
                output_text=resp.text[:2000],
                tokens=resp.tokens,
                success=resp.success,
            ))
            if resp.success:
                specialist_results.append(f"=== {label} ===\n{resp.text[:2000]}")

        await asyncio.gather(
            *[run_specialist(a, n, lbl) for a, n, lbl in spec_list]
        )

        return f"Отдел сайта завершил работу.\n\n" + "\n\n".join(specialist_results)

    # ── AI Solutions: анализ клиента, КП, брейншторм ──

    @staticmethod
    def _should_route_client_solutions(message: str) -> bool:
        low = message.lower()
        return any(kw in low for kw in client_solutions_trigger_keywords())

    async def run_client_analysis(
        self,
        owner_message: str,
        task_id: int | None = None,
        task_mode: str | None = None,
        progress: TaskProgress | None = None,
    ) -> OrchestratorResult:
        """
        Пайплайн AI Solutions: последовательные вызовы (rate limits).
        lite — только ClientCEO + AIStrategist + синтез; standard/full — + Crisis + PM.
        """
        start_time = time.time()
        chain: list[AgentExecution] = []
        content_ids: list[int] = []

        own_task_progress = progress is None
        if task_id is None:
            task_id = await create_task(owner_message)
        if progress is None:
            progress = TaskProgress(task_id)
            self._active_tasks[task_id] = progress
            await update_task(task_id, status="running")

        eff_mode = self._resolve_task_mode(None, task_mode)

        footer = (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Готов к брейншторму. Команды в Telegram:\n"
            "/approve_kp — сгенерировать КП\n"
            "/brainstorm [вопрос] — уточнить анализ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        try:
            await progress.emit({
                "stage": "ai_solutions",
                "agent": "client_ceo",
                "message": "Шаг 1/3: стратегия клиента (Client CEO)...",
            })
            ceo = await self.team.client_ceo.think(
                task_input=(
                    f"Ситуация и запрос владельца агентства по клиенту:\n\n{owner_message}\n\n"
                    "Дай Executive Summary и Top-3 приоритета (см. твою роль)."
                ),
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name="client_ceo",
                role=self.team.client_ceo.role,
                input_brief=owner_message[:500],
                output_text=ceo.text[:2000],
                tokens=ceo.tokens,
                success=ceo.success,
            ))
            if not ceo.success:
                await update_task(
                    task_id, status="error", error=ceo.error,
                    duration=time.time() - start_time,
                )
                await progress.emit({"stage": "error", "agent": "client_ceo", "message": str(ceo.error)})
                await progress.complete()
                return OrchestratorResult(
                    task_id=task_id,
                    success=False,
                    final_report=f"Ошибка Client CEO: {ceo.error}",
                    chain=chain,
                    content_ids=[],
                    duration_seconds=time.time() - start_time,
                )

            await progress.emit({
                "stage": "ai_solutions",
                "agent": "ai_strategist",
                "message": "Шаг 1/3: техническая архитектура (AI Strategist)...",
            })
            arch1 = await self.team.ai_strategist.think(
                task_input=(
                    f"Исходный запрос владельца:\n{owner_message}\n\n"
                    f"Стратегический разбор Client CEO:\n{ceo.text}\n\n"
                    "Предложи стек, сроки (дни), бюджеты (₽), владение/мес, риски и митигацию."
                ),
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name="ai_strategist",
                role=self.team.ai_strategist.role,
                input_brief="Архитектура (шаг 1)",
                output_text=arch1.text[:2000],
                tokens=arch1.tokens,
                success=arch1.success,
            ))
            if not arch1.success:
                await update_task(
                    task_id, status="error", error=arch1.error,
                    duration=time.time() - start_time,
                )
                await progress.complete()
                return OrchestratorResult(
                    task_id=task_id,
                    success=False,
                    final_report=f"Ошибка AI Strategist: {arch1.error}",
                    chain=chain,
                    content_ids=[],
                    duration_seconds=time.time() - start_time,
                )

            crisis_text = ""
            pm_text = ""
            if eff_mode == "lite":
                crisis_text = (
                    "(В режиме lite блок антикризиса не выполнялся — только CEO + Architect.)"
                )
                pm_text = "(В режиме lite полный roadmap не строился.)"
            else:
                await progress.emit({
                    "stage": "ai_solutions",
                    "agent": "crisis_manager",
                    "message": "Шаг 2/3: риски (Crisis Manager)...",
                })
                crisis = await self.team.crisis_manager.think(
                    task_input=(
                        f"Запрос:\n{owner_message[:4000]}\n\n=== CEO ===\n{ceo.text[:6000]}\n\n"
                        f"=== Architect ===\n{arch1.text[:6000]}"
                    ),
                    task_id=task_id,
                )
                chain.append(AgentExecution(
                    agent_name="crisis_manager",
                    role=self.team.crisis_manager.role,
                    input_brief="Риски",
                    output_text=crisis.text[:2000],
                    tokens=crisis.tokens,
                    success=crisis.success,
                ))
                crisis_text = crisis.text if crisis.success else f"(Ошибка: {crisis.error})"

                await progress.emit({
                    "stage": "ai_solutions",
                    "agent": "solutions_pm",
                    "message": "Шаг 2/3: roadmap (Solutions PM)...",
                })
                pm = await self.team.solutions_pm.think(
                    task_input=(
                        f"Запрос:\n{owner_message[:3000]}\n\n=== CEO ===\n{ceo.text[:5000]}\n\n"
                        f"=== Architect ===\n{arch1.text[:5000]}\n\n=== Риски ===\n{crisis_text[:5000]}"
                    ),
                    task_id=task_id,
                )
                chain.append(AgentExecution(
                    agent_name="solutions_pm",
                    role=self.team.solutions_pm.role,
                    input_brief="Roadmap",
                    output_text=pm.text[:2000],
                    tokens=pm.tokens,
                    success=pm.success,
                ))
                pm_text = pm.text if pm.success else f"(Ошибка: {pm.error})"

            await progress.emit({
                "stage": "ai_solutions",
                "agent": "ai_strategist",
                "message": "Шаг 3/3: итоговый синтез...",
            })
            synthesis_prompt = f"""На основе материалов ниже собери **единый итоговый отчёт для владельца агентства**
строго по структуре:

━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 СУТЬ ПРОБЛЕМЫ КЛИЕНТА
━━━━━━━━━━━━━━━━━━━━━━━━━
(корень проблемы и потери — из CEO)

💡 ТОП-3 СЦЕНАРИЯ РЕШЕНИЙ
━━━━━━━━━━━━━━━━━━━━━━━━━
Сценарий 1: [название] — РЕКОМЕНДУЕМЫЙ
  Стек: ...
  Срок MVP: X дней | Полное: X дней
  Стоимость: X руб | Владение: X руб/мес
  ROI: окупается за X месяцев (оценка)

Сценарий 2: [название] — БЮДЖЕТНЫЙ
  ...

Сценарий 3: [название] — МАКСИМАЛЬНЫЙ
  ...

⚠️ КЛЮЧЕВЫЕ РИСКИ
━━━━━━━━━━━━━━━━━━━━━━━━━
(топ-3 с митигацией)

📅 ROADMAP (рекомендуемый сценарий)
━━━━━━━━━━━━━━━━━━━━━━━━━
Этап 1: ... — X дней — X руб
...
ИТОГО: X дней | X руб

=== ВХОДНЫЕ МАТЕРИАЛЫ ===
--- CEO ---
{ceo.text[:8000]}

--- Architect (шаг 1) ---
{arch1.text[:8000]}

--- Риски ---
{crisis_text[:6000]}

--- Roadmap PM ---
{pm_text[:8000]}
"""
            final_r = await self.team.ai_strategist.think(
                task_input=synthesis_prompt,
                task_id=task_id,
            )
            chain.append(AgentExecution(
                agent_name="ai_strategist",
                role="AI Strategist (синтез)",
                input_brief="Итоговый отчёт",
                output_text=final_r.text[:3000],
                tokens=final_r.tokens,
                success=final_r.success,
            ))

            if not final_r.success:
                await update_task(
                    task_id, status="error", error=final_r.error,
                    duration=time.time() - start_time,
                )
                await progress.complete()
                return OrchestratorResult(
                    task_id=task_id,
                    success=False,
                    final_report=f"Ошибка синтеза: {final_r.error}",
                    chain=chain,
                    content_ids=[],
                    duration_seconds=time.time() - start_time,
                )

            final_text = final_r.text.strip() + footer
            duration = time.time() - start_time

            cid = await save_content(
                task_id=task_id,
                channel="client_analysis",
                topic="AI Solutions — итоговый отчёт",
                body=final_text[:100_000],
                rubric="ai_solutions",
            )
            content_ids.append(cid)

            await update_task(
                task_id,
                status="done",
                result=final_text[:12_000],
                duration=duration,
            )

            await progress.emit({
                "stage": "done",
                "agent": "system",
                "message": f"AI Solutions: задача #{task_id} завершена за {duration:.1f}с",
            })
            await progress.complete()

            return OrchestratorResult(
                task_id=task_id,
                success=True,
                final_report=final_text,
                chain=chain,
                content_ids=content_ids,
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error("run_client_analysis #%s: %s", task_id, e, exc_info=True)
            duration = time.time() - start_time
            await update_task(task_id, status="error", error=str(e), duration=duration)
            await progress.emit({"stage": "error", "agent": "system", "message": str(e)})
            await progress.complete()
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report=f"Ошибка AI Solutions: {str(e)}",
                chain=chain,
                content_ids=[],
                duration_seconds=duration,
            )
        finally:
            if own_task_progress:
                self._active_tasks.pop(task_id, None)

    async def generate_client_kp(self, task_id: int) -> OrchestratorResult:
        """КП только по явному запросу (после согласования анализа)."""
        start_time = time.time()
        chain: list[AgentExecution] = []

        task = await get_task(task_id)
        if not task:
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report="Задача не найдена.",
                chain=[],
                content_ids=[],
                duration_seconds=time.time() - start_time,
            )

        rows = await get_content_for_task(task_id)
        bodies = [r["body"] for r in rows if r.get("channel") == "client_analysis"]
        bundle = "\n\n---\n\n".join(bodies) if bodies else (task.get("result") or "")
        if not bundle.strip():
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report="Нет сохранённого анализа (client_analysis). Сначала выполни анализ клиента.",
                chain=[],
                content_ids=[],
                duration_seconds=time.time() - start_time,
            )

        kp = await self.team.kp_writer.think(
            task_input=(
                "Владелец подтвердил готовность к коммерческому предложению. "
                "Составь КП по структуре из твоей роли на основе материалов:\n\n"
                f"{bundle[:24000]}"
            ),
            task_id=task_id,
        )
        chain.append(AgentExecution(
            agent_name="kp_writer",
            role=self.team.kp_writer.role,
            input_brief="КП по анализу",
            output_text=kp.text[:3000],
            tokens=kp.tokens,
            success=kp.success,
        ))

        if not kp.success:
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report=f"Ошибка KP Writer: {kp.error}",
                chain=chain,
                content_ids=[],
                duration_seconds=time.time() - start_time,
            )

        cid = await save_content(
            task_id=task_id,
            channel="client_kp",
            topic="Коммерческое предложение (AI Solutions)",
            body=kp.text[:100_000],
            rubric="ai_solutions",
        )
        duration = time.time() - start_time
        combined = (task.get("result") or "") + "\n\n--- КП ---\n\n" + kp.text
        await update_task(task_id, result=combined[:12_000])

        return OrchestratorResult(
            task_id=task_id,
            success=True,
            final_report=kp.text,
            chain=chain,
            content_ids=[cid],
            duration_seconds=duration,
        )

    async def run_client_brainstorm(self, task_id: int, question: str) -> OrchestratorResult:
        """Доп. итерация: CEO + Architect по вопросу владельца."""
        start_time = time.time()
        chain: list[AgentExecution] = []
        content_ids: list[int] = []

        task = await get_task(task_id)
        if not task:
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report="Задача не найдена.",
                chain=[],
                content_ids=[],
                duration_seconds=time.time() - start_time,
            )

        prev = (task.get("result") or "").strip()
        q = question.strip()
        if not q:
            return OrchestratorResult(
                task_id=task_id,
                success=False,
                final_report="Пустой вопрос.",
                chain=[],
                content_ids=[],
                duration_seconds=time.time() - start_time,
            )

        brief_ceo = (
            f"Предыдущий отчёт по клиенту (фрагмент):\n{prev[:8000]}\n\n"
            f"Уточняющий вопрос владельца агентства:\n{q}\n\n"
            "Дай углублённый ответ в формате своей роли."
        )
        ceo = await self.team.client_ceo.think(task_input=brief_ceo, task_id=task_id)
        chain.append(AgentExecution(
            agent_name="client_ceo",
            role=self.team.client_ceo.role + " (брейншторм)",
            input_brief=q[:500],
            output_text=ceo.text[:2000],
            tokens=ceo.tokens,
            success=ceo.success,
        ))

        arch_in = (
            f"Вопрос владельца:\n{q}\n\nОтвет Client CEO:\n{ceo.text[:8000]}\n\n"
            f"Контекст отчёта:\n{prev[:4000]}"
        )
        arch = await self.team.ai_strategist.think(task_input=arch_in, task_id=task_id)
        chain.append(AgentExecution(
            agent_name="ai_strategist",
            role=self.team.ai_strategist.role + " (брейншторм)",
            input_brief=q[:500],
            output_text=arch.text[:2000],
            tokens=arch.tokens,
            success=arch.success,
        ))

        block = (
            f"\n\n--- Брейншторм ---\nВопрос: {q}\n\n### Client CEO\n{ceo.text}\n\n"
            f"### AI Architect\n{arch.text}\n"
        )
        new_result = (prev + block).strip()[:48_000]
        await update_task(task_id, result=new_result[:12_000])

        cid = await save_content(
            task_id=task_id,
            channel="client_analysis",
            topic=f"brainstorm: {q[:100]}",
            body=block[:50_000],
            rubric="ai_solutions",
        )
        content_ids.append(cid)

        duration = time.time() - start_time
        return OrchestratorResult(
            task_id=task_id,
            success=ceo.success and arch.success,
            final_report=block,
            chain=chain,
            content_ids=content_ids,
            duration_seconds=duration,
        )

    async def run_daily_cycle(self) -> dict:
        """
        Автономный дневной цикл без команды владельца.
        Создаёт Telegram-пост и Threads-пост.
        """
        logger.info("Запуск дневного цикла контента")
        results = {}

        try:
            task_id = await create_task("Автоматический дневной цикл контента")
            await update_task(task_id, status="running")

            # Telegram-пост
            tg = await self.team.telegram_writer.think(
                task_input=(
                    "Напиши ежедневный пост для Telegram-канала агентства. "
                    "Выбери актуальную тему из области ИИ-автоматизации для бизнеса. "
                    "Рубрика на твой выбор: кейс, инсайт, инструмент или мнение."
                ),
                task_id=task_id,
            )
            if tg.success:
                qa = await self.team.qa_editor.qa_check(tg.text, "telegram", task_id)
                final_text = qa.text if qa.success else tg.text
                cid = await save_content(task_id, "telegram", "Дневной пост", final_text, "auto")
                results["telegram"] = {"content_id": cid, "success": True}
            else:
                results["telegram"] = {"success": False, "error": tg.error}

            # Threads-пост
            th = await self.team.threads_writer.think(
                task_input=(
                    "Напиши ежедневный пост для Threads. "
                    "Тема: ИИ и автоматизация для бизнеса. "
                    "Короткий, живой, разговорный."
                ),
                task_id=task_id,
            )
            if th.success:
                cid = await save_content(task_id, "threads", "Дневной пост", th.text, "auto")
                results["threads"] = {"content_id": cid, "success": True}
            else:
                results["threads"] = {"success": False, "error": th.error}

            await update_task(task_id, status="done", result=json.dumps(results, ensure_ascii=False))
            logger.info("Дневной цикл завершён: %s", results)

        except Exception as e:
            logger.error("Ошибка дневного цикла: %s", e, exc_info=True)
            results["error"] = str(e)

        return results

    async def run_weekly_report(self) -> dict:
        """Еженедельный отчёт с метриками."""
        logger.info("Формирование еженедельного отчёта")
        try:
            metrics = await get_metrics()

            report_response = await self.team.chief.think(
                task_input=(
                    f"Сформируй еженедельный отчёт для владельца на основе метрик:\n\n"
                    f"{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n"
                    "Включи: общее состояние, ключевые цифры, рекомендации на следующую неделю."
                ),
            )

            today = date.today().isoformat()
            report_data = {
                "metrics": metrics,
                "report_text": report_response.text,
                "generated_at": datetime.utcnow().isoformat(),
            }
            await save_report("weekly", today, report_data)

            return {
                "success": True,
                "report": report_response.text,
                "metrics": metrics,
            }

        except Exception as e:
            logger.error("Ошибка еженедельного отчёта: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_task_status(self, task_id: int) -> dict:
        """Статус и прогресс задачи."""
        task = await get_task(task_id)
        if not task:
            return {"error": "Задача не найдена"}

        chain = await get_task_chain(task_id)
        content = await get_content_for_task(task_id)

        progress_tracker = self._active_tasks.get(task_id)
        current_steps = progress_tracker.steps if progress_tracker else []

        return {
            "task": task,
            "chain": chain,
            "content": content,
            "live_progress": current_steps,
            "is_running": task_id in self._active_tasks,
        }

    def _parse_chief_plan(self, text: str) -> dict:
        """Извлечь JSON-план: departments, task_mode, primary_agent, primary_brief."""
        meta = {
            "task_mode": None,
            "primary_agent": None,
            "primary_brief": None,
        }
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                meta["task_mode"] = data.get("task_mode")
                meta["primary_agent"] = data.get("primary_agent")
                meta["primary_brief"] = data.get("primary_brief")
                raw_depts = data.get("departments")
                if isinstance(raw_depts, dict):
                    depts = raw_depts
                else:
                    depts = {
                        k: data[k]
                        for k in ("content", "research", "product", "website")
                        if k in data
                    }
                out = {**meta}
                for key in ("content", "research", "product", "website"):
                    if key in depts:
                        out[key] = depts[key]
                if not any(
                    isinstance(out.get(k), dict)
                    for k in ("content", "research", "product", "website")
                ):
                    text_lower = text.lower()
                    for dept in ("content", "research", "product", "website"):
                        if dept in text_lower or self._dept_alias(dept) in text_lower:
                            out[dept] = {"needed": True, "brief": text}
                    if not any(
                        isinstance(out.get(k), dict)
                        for k in ("content", "research", "product", "website")
                    ):
                        out["content"] = {"needed": True, "brief": text}
                return out
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        plan = dict(meta)
        text_lower = text.lower()
        for dept in ("content", "research", "product", "website"):
            if dept in text_lower or self._dept_alias(dept) in text_lower:
                plan[dept] = {"needed": True, "brief": text}
        if not any(
            isinstance(plan.get(k), dict)
            for k in ("content", "research", "product", "website")
        ):
            plan["content"] = {"needed": True, "brief": text}
        return plan

    @staticmethod
    def _resolve_task_mode(chief_mode: str | None, override: str | None) -> str:
        if override and override.strip().lower() in ("lite", "standard", "full"):
            return override.strip().lower()
        if chief_mode and str(chief_mode).strip().lower() in ("lite", "standard", "full"):
            return str(chief_mode).strip().lower()
        default = os.getenv("DEFAULT_TASK_MODE", "lite").strip().lower()
        if default in ("lite", "standard", "full"):
            return default
        return "lite"

    @staticmethod
    def _infer_lite_agent(dept_name: str) -> str:
        return {
            "content": "telegram_writer",
            "research": "market_analyst",
            "product": "offer_strategist",
            "website": "web_copywriter",
        }.get(dept_name, "telegram_writer")

    @staticmethod
    def _dept_alias(dept: str) -> str:
        aliases = {
            "content": "контент",
            "research": "аналитик",
            "product": "продукт",
            "website": "сайт",
        }
        return aliases.get(dept, dept)
