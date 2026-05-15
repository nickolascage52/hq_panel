"""
Контекст агентства и структура команды.

Контекст агентства загружается динамически через agency_context_loader.
Этот модуль содержит только TEAM_STRUCTURE (структура команды — часть кода)
и функцию-обёртку get_agency_context_text() для обратной совместимости.
"""


TEAM_STRUCTURE = {
    "ai_solutions_dept": {
        "head": "ai_strategist",
        "members": [
            "client_ceo",
            "crisis_manager",
            "solutions_pm",
            "kp_writer",
            "b2b_specialist",
        ],
        "trigger_keywords": [
            "клиент",
            "решение для",
            "автоматизировать",
            "внедрить",
            "кп",
            "коммерческое",
            "аудит бизнеса",
            "проблема клиента",
            "бизнес клиента",
            "коммерческое предложение",
            "b2b",
            "лидоген",
            "воронк",
            "квалификац",
            "возражен",
            "продаж",
        ],
    },
    "chief_of_staff": {
        "role": "Chief of Staff",
        "responsibilities": [
            "Приём задач от владельца и декомпозиция",
            "Распределение задач по отделам",
            "Контроль качества и сроков",
            "Формирование итоговых отчётов",
            "Принятие решений о приоритетах",
        ],
        "delegates_to": [
            "content_director",
            "research_head",
            "product_manager",
            "website_strategist",
            "ai_solutions_dept",
        ],
    },
    "department_heads": {
        "content_director": {
            "role": "Контент-директор",
            "department": "Контент",
            "responsibilities": [
                "Контент-стратегия по всем каналам",
                "Редакционный календарь",
                "Контроль качества текстов",
                "Адаптация контента под платформу",
            ],
            "manages": [
                "telegram_writer",
                "threads_writer",
                "vc_writer",
                "qa_editor",
            ],
        },
        "research_head": {
            "role": "Руководитель аналитики",
            "department": "Аналитика",
            "responsibilities": [
                "Исследование рынка и трендов",
                "Анализ конкурентов",
                "Поиск инсайтов для контента и продукта",
                "Data-driven рекомендации",
            ],
            "manages": [
                "market_analyst",
                "competitor_analyst",
                "trend_analyst",
            ],
        },
        "product_manager": {
            "role": "Продакт-менеджер",
            "department": "Продукт",
            "responsibilities": [
                "Развитие продуктовой линейки",
                "Тестирование гипотез",
                "Оптимизация офферов",
                "Ценообразование",
            ],
            "manages": [
                "offer_strategist",
                "hypothesis_analyst",
            ],
        },
        "website_strategist": {
            "role": "Стратег по сайту",
            "department": "Сайт",
            "responsibilities": [
                "Конверсионная оптимизация сайта",
                "UX/UI рекомендации",
                "Копирайтинг для сайта",
                "A/B тестирование",
            ],
            "manages": [
                "cro_analyst",
                "web_copywriter",
            ],
        },
    },
    "specialists": {
        "telegram_writer": {
            "role": "Telegram-копирайтер",
            "department": "Контент",
            "reports_to": "content_director",
        },
        "threads_writer": {
            "role": "Threads-копирайтер",
            "department": "Контент",
            "reports_to": "content_director",
        },
        "vc_writer": {
            "role": "VC.ru-автор",
            "department": "Контент",
            "reports_to": "content_director",
        },
        "qa_editor": {
            "role": "QA-редактор",
            "department": "Контент",
            "reports_to": "content_director",
        },
        "market_analyst": {
            "role": "Рыночный аналитик",
            "department": "Аналитика",
            "reports_to": "research_head",
        },
        "competitor_analyst": {
            "role": "Аналитик конкурентов",
            "department": "Аналитика",
            "reports_to": "research_head",
        },
        "trend_analyst": {
            "role": "Трендовый аналитик",
            "department": "Аналитика",
            "reports_to": "research_head",
        },
        "offer_strategist": {
            "role": "Стратег по офферам",
            "department": "Продукт",
            "reports_to": "product_manager",
        },
        "hypothesis_analyst": {
            "role": "Аналитик гипотез",
            "department": "Продукт",
            "reports_to": "product_manager",
        },
        "cro_analyst": {
            "role": "CRO-аналитик",
            "department": "Сайт",
            "reports_to": "website_strategist",
        },
        "web_copywriter": {
            "role": "Веб-копирайтер",
            "department": "Сайт",
            "reports_to": "website_strategist",
        },
        "client_ceo": {
            "role": "Client CEO (стратегия клиента)",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
        "ai_strategist": {
            "role": "AI Solutions Architect",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
        "crisis_manager": {
            "role": "Антикризис и риски",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
        "solutions_pm": {
            "role": "PM ИИ-проектов (roadmap)",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
        "kp_writer": {
            "role": "Автор КП",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
        "b2b_specialist": {
            "role": "B2B Sales Specialist",
            "department": "AI Solutions",
            "reports_to": "chief_of_staff",
        },
    },
}


def client_solutions_trigger_keywords() -> tuple[str, ...]:
    """Ключевые слова для маршрутизации в отдел AI Solutions."""
    dept = TEAM_STRUCTURE.get("ai_solutions_dept") or {}
    kws = dept.get("trigger_keywords") or []
    return tuple(str(k).lower() for k in kws)


def get_agency_context_text() -> str:
    """
    Возвращает актуальный контекст агентства из единого источника.
    Приоритет: загруженный файл → 00_MASTER/*.md → шаблон по умолчанию.
    """
    from agency_context_loader import get_agency_context
    return get_agency_context()
