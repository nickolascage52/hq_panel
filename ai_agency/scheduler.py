"""
Планировщик задач на asyncio + schedule.
Запускает дневные и недельные циклы по расписанию.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import schedule

from database import format_focus_brief_text
from orchestrator import Orchestrator

logger = logging.getLogger("scheduler")

try:
    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    # Windows без пакета tzdata: IANA-зоны недоступны; МСК с 2014 — постоянно UTC+3
    MOSCOW_TZ = timezone(timedelta(hours=3), "MSK")
    logger.warning(
        "ZoneInfo(Europe/Moscow) недоступен (установите: pip install tzdata). "
        "Планировщик использует фиксированное UTC+3 (МСК)."
    )


class AgencyScheduler:
    """Планировщик фоновых задач агентства."""

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self._running = False
        self._pending_jobs: list[asyncio.Task] = []
        self._last_focus_brief_date: str | None = None

    def setup(self):
        """Настроить расписание."""
        daily_time = os.getenv("DAILY_POST_TIME", "09:00")
        auto_publish = os.getenv("AUTO_PUBLISH", "false").lower() == "true"

        if auto_publish:
            schedule.every().day.at(daily_time).do(self._schedule_daily_cycle)
            logger.info("Дневной цикл контента запланирован на %s", daily_time)
        else:
            logger.info(
                "Автопубликация отключена (AUTO_PUBLISH=false). "
                "Дневной цикл не запланирован."
            )

        schedule.every().sunday.at("18:00").do(self._schedule_weekly_report)
        logger.info("Еженедельный отчёт запланирован: воскресенье 18:00")

        logger.info("Утренний брифинг HQ: ежедневно ~9:00 МСК, кроме четверга (проверка в цикле)")

    def _schedule_daily_cycle(self):
        """Поставить дневной цикл в очередь (вызывается schedule)."""
        logger.info("Планировщик: запуск дневного цикла")
        task = asyncio.ensure_future(self._run_daily_cycle())
        self._pending_jobs.append(task)

    def _schedule_weekly_report(self):
        """Поставить еженедельный отчёт в очередь."""
        logger.info("Планировщик: запуск еженедельного отчёта")
        task = asyncio.ensure_future(self._run_weekly_report())
        self._pending_jobs.append(task)

    async def _run_daily_cycle(self):
        """Выполнить дневной цикл и отправить уведомление."""
        try:
            result = await self.orchestrator.run_daily_cycle()
            logger.info("Дневной цикл завершён: %s", result)
            await self._notify_owner(
                f"📅 Дневной цикл контента завершён\n\n"
                f"Telegram: {'✅' if result.get('telegram', {}).get('success') else '❌'}\n"
                f"Threads: {'✅' if result.get('threads', {}).get('success') else '❌'}"
            )
        except Exception as e:
            logger.error("Ошибка дневного цикла: %s", e, exc_info=True)
            await self._notify_owner(f"❌ Ошибка дневного цикла: {e}")

    async def _run_weekly_report(self):
        """Выполнить еженедельный отчёт и отправить владельцу."""
        try:
            result = await self.orchestrator.run_weekly_report()
            if result.get("success"):
                await self._notify_owner(
                    f"📊 Еженедельный отчёт\n\n{result['report']}"
                )
            else:
                await self._notify_owner(
                    f"❌ Ошибка формирования отчёта: {result.get('error')}"
                )
        except Exception as e:
            logger.error("Ошибка еженедельного отчёта: %s", e, exc_info=True)

    async def _maybe_morning_focus_brief(self) -> None:
        """Один раз в день в 9:00–9:05 по Москве, не по четвергам."""
        now = datetime.now(MOSCOW_TZ)
        if now.weekday() == 3:
            return
        if now.hour != 9 or now.minute > 5:
            return
        dkey = now.date().isoformat()
        if self._last_focus_brief_date == dkey:
            return
        self._last_focus_brief_date = dkey
        try:
            body = await format_focus_brief_text()
            await self._notify_owner("☀️ Утренний брифинг HQ\n\n" + body)
        except Exception as e:
            logger.error("Утренний брифинг: %s", e, exc_info=True)

    async def _notify_owner(self, text: str):
        """Отправить уведомление владельцу через Telegram."""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        owner_id = os.getenv("TELEGRAM_OWNER_ID", "")

        if not bot_token or not owner_id or bot_token == "ЗАМЕНИ_НА_ТОКЕН_БОТА":
            logger.warning("Telegram не настроен — уведомление не отправлено")
            return

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            max_len = 4000
            parts = []
            remaining = text
            while remaining:
                if len(remaining) <= max_len:
                    parts.append(remaining)
                    break
                cut = remaining[:max_len].rfind("\n")
                if cut < max_len // 2:
                    cut = max_len
                parts.append(remaining[:cut])
                remaining = remaining[cut:].lstrip("\n")

            async with aiohttp.ClientSession() as session:
                for part in parts:
                    await session.post(url, json={
                        "chat_id": owner_id,
                        "text": part,
                    })
        except Exception as e:
            logger.error("Ошибка отправки уведомления: %s", e)

    async def run(self):
        """Главный цикл планировщика."""
        self.setup()
        self._running = True
        logger.info("Планировщик запущен")

        try:
            while self._running:
                schedule.run_pending()
                await self._maybe_morning_focus_brief()
                self._pending_jobs = [t for t in self._pending_jobs if not t.done()]
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("Планировщик останавливается...")
            for task in self._pending_jobs:
                task.cancel()
            self._running = False

    def stop(self):
        self._running = False
