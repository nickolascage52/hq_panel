"""
Точка входа AI Agency Management System.
По умолчанию: FastAPI, Telegram-бот, планировщик.

Рабочие панели открываются только здесь (uvicorn), не через python -m http.server:
  http://127.0.0.1:8000/       → редирект на HQ (/hq/)
  http://127.0.0.1:8000/hq/    — дашборд, CRM, AI Команда, аналитика, аккаунт
  http://127.0.0.1:8000/hq/team.html — чат с агентами и задача всей команде
  http://127.0.0.1:8000/admin  — редирект на /hq/team.html (старый URL)
  http://127.0.0.1:8000/panel  — то же
  http://127.0.0.1:8000/service/ — маркетинговая страница «AI команда»

Локально без бота: в .env задайте WEB_ONLY=true или: set WEB_ONLY=1 && python main.py
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

# Экспорт FastAPI-приложения для `uvicorn main:app` и Playwright webServer.
from api import app


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def web_only_mode() -> bool:
    """Только API + статика (без Telegram polling и планировщика)."""
    return _env_truthy("WEB_ONLY") or _env_truthy("API_ONLY")


def check_env():
    """Проверить наличие критичных переменных окружения."""
    required = {
        "ANTHROPIC_API_KEY": "Claude API ключ",
    }
    recommended = {
        "TELEGRAM_BOT_TOKEN": "Telegram бот токен",
        "TELEGRAM_OWNER_ID": "Telegram ID владельца",
        "ADMIN_PASSWORD": "Пароль для API панели",
    }

    missing_required = []
    missing_recommended = []

    for var, desc in required.items():
        val = os.getenv(var, "")
        if not val or val.startswith("ЗАМЕНИ") or val.startswith("sk-ant-ЗАМЕНИ"):
            missing_required.append(f"  - {var}: {desc}")

    for var, desc in recommended.items():
        val = os.getenv(var, "")
        if not val or val.startswith("ЗАМЕНИ"):
            missing_recommended.append(f"  - {var}: {desc}")

    if missing_required:
        logger.error(
            "КРИТИЧЕСКИЕ переменные не заданы:\n%s\n"
            "Заполни файл .env и перезапусти.",
            "\n".join(missing_required),
        )
        sys.exit(1)

    if missing_recommended:
        logger.warning(
            "Рекомендуемые переменные не заданы (система запустится, но с ограничениями):\n%s",
            "\n".join(missing_recommended),
        )


async def start_api_server():
    """Запустить FastAPI через uvicorn."""
    import uvicorn
    from api import app

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    logger.info("FastAPI сервер запускается на %s:%d", host, port)
    await server.serve()


async def start_telegram_bot(orchestrator):
    """Запустить Telegram-бот."""
    from telegram_bot import run_bot
    await run_bot(orchestrator)


async def start_scheduler(orchestrator):
    """Запустить планировщик."""
    from scheduler import AgencyScheduler
    sched = AgencyScheduler(orchestrator)
    await sched.run()


async def _run_optional_component(component_name: str, run_coro):
    """
    Ошибка бота/планировщика не должна гасить uvicorn (например таймаут до api.telegram.org).
    """
    try:
        await run_coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(
            "Компонент «%s» остановлен: %s. FastAPI и HQ продолжают работу. "
            "Если Telegram недоступен из сети — VPN или WEB_ONLY=true в .env.",
            component_name,
            exc,
            exc_info=exc,
        )
        while True:
            await asyncio.sleep(3600)


async def main():
    """Главная функция — запуск всех компонентов."""
    logger.info("=" * 60)
    logger.info("  AI Agency Management System")
    logger.info("  Версия 1.0")
    logger.info("=" * 60)

    check_env()

    from database import init_db
    await init_db()
    logger.info("База данных готова")

    from orchestrator import Orchestrator
    orchestrator = Orchestrator()

    from api import orchestrator as api_orch_ref
    import api
    api.orchestrator = orchestrator

    team_list = orchestrator.team.list_agents()
    logger.info("Команда загружена: %d агентов", len(team_list))
    for agent_info in team_list:
        logger.info("  [%s] %s — %s", agent_info["department"], agent_info["name"], agent_info["role"])

    logger.info("-" * 60)
    logger.info("Запуск компонентов...")

    web_only = web_only_mode()
    tasks = [asyncio.create_task(start_api_server(), name="api_server")]
    if not web_only:
        tasks.append(
            asyncio.create_task(
                _run_optional_component("telegram_bot", start_telegram_bot(orchestrator)),
                name="telegram_bot",
            )
        )
        tasks.append(
            asyncio.create_task(
                _run_optional_component("scheduler", start_scheduler(orchestrator)),
                name="scheduler",
            )
        )

    logger.info("Все компоненты запущены:")
    logger.info("  [API]       http://%s:%s", os.getenv("HOST", "0.0.0.0"), os.getenv("PORT", "8000"))
    if web_only:
        logger.info("  [Режим]     WEB_ONLY — Telegram и планировщик отключены (нет конфликта с ботом на сервере)")
        logger.info("  [HQ]        http://127.0.0.1:%s/hq/  (дашборд, CRM, AI Команда)", os.getenv("PORT", "8000"))
        logger.info("  [Корень]    http://127.0.0.1:%s/  → редирект на /hq/", os.getenv("PORT", "8000"))
        logger.info("  [Старые URL] /admin и /panel → /hq/team.html")
        logger.info("  [Лендинг]   http://127.0.0.1:%s/service/", os.getenv("PORT", "8000"))
    else:
        logger.info("  [Telegram]  Бот ожидает сообщений")
        logger.info("  [Scheduler] Планировщик активен")
        logger.info("  [HQ]        http://127.0.0.1:%s/hq/  |  /service/ — лендинг",
                    os.getenv("PORT", "8000"))
    logger.info("=" * 60)

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        for task in done:
            if task.exception():
                logger.error(
                    "Компонент %s упал: %s",
                    task.get_name(),
                    task.exception(),
                    exc_info=task.exception(),
                )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Система остановлена.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
