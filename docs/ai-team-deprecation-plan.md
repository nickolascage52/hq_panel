# AI Team Deprecation Plan (T-5-001/002, Sprint 5)

**Дата:** 2026-05-15
**Автор:** Sprint 5 audit
**Стратегия:** старая AI Команда (`ai_agency/agents/`, `orchestrator.py`, и связанные UI/API endpoints) переходит в режим **legacy — оставлено как есть до v2.0**.

---

## Что входит в "старую AI Команду"

### Code модули

| Файл | Роль | Что использует |
|---|---|---|
| `ai_agency/agents/team.py` | 23 prompt-агента (ChiefOfStaff, ContentDirector, ...) | `orchestrator.py` |
| `ai_agency/agents/base.py` | AgentBase, AgentResponse — общий класс | `team.py` |
| `ai_agency/agents/context.py` | роутинг ключевых слов в AI Solutions | `team.py`, `orchestrator.py` |
| `ai_agency/agents/request_context.py` | ContextVar для override модели | `base.py` |
| `ai_agency/orchestrator.py` | `Orchestrator.run_task()`, режимы lite/standard/full | `main.py`, `telegram_bot.py`, `api.py` |
| `ai_agency/agency_context_loader.py` | контекст агентства, кэш 60с | агенты, новый pipeline тоже его использует |
| `ai_agency/scheduler.py` | дневной/недельный циклы (вызывают orchestrator) | `main.py` |

### API endpoints (старые, в `api.py`)

| Эндпоинт | Метод | Использование |
|---|---|---|
| `/api/task` | POST | Старая постановка задачи команде через orchestrator |
| `/api/task/{id}` | GET | Статус |
| `/api/tasks` | GET | Список |
| `/api/tasks/{id}/messages` | GET | Сообщения внутри задачи |
| `/ws/task/{id}` | WS | Стриминг прогресса (TaskProgress) |
| `/api/agents/{name}/chat` | POST | Прямой чат с агентом |
| `/api/agents/{name}/chat/history` | GET | История чата |
| `/api/status` | GET | Состояние системы (использует Orchestrator статус) |

### Frontend (страницы которые зависят)

| Страница | Зависит от |
|---|---|
| `static/hq/team.html` | `/api/agents/{name}/chat`, `/api/agents/{name}/chat/history`, `/api/task`, `/ws/task/{id}` |
| `static/hq/team-settings.html` | `/api/panel/settings` (модели агентов) |
| `static/hq/index.html` | Дашборд читает `/api/status`, agent_executions counters |
| `static/hq/notes.html` | конвертирует note → task через `/api/task` |
| `static/hq/channel.html` | Возможно использует agent для генерации постов |

### Telegram bot (`telegram_bot.py`)

| Команда | Использует AI Команду? |
|---|---|
| `/start` | Нет |
| `/help` | Нет |
| `/report` | **Да** (формирует отчёт через ChiefOfStaff если есть AI; иначе deterministic) |
| `/clients` | Нет (DB-only) |
| `/students` | Нет (DB-only) |
| `/finance` | Нет (DB-only) |
| `/deadlines` | Нет (DB-only) |
| `/agent <name> <text>` | **Да** (прямой вызов orchestrator) |
| Любой текст | **Да** (маршрутизация в `Orchestrator.run_task()`) |

---

## Решение по Telegram (T-5-002)

### Выбран Вариант A: оставить как есть

Аргументы:
1. **Telegram bot работает stable** — `/report`, `/clients`, `/students`, `/finance`, `/deadlines` не зависят от AI и продолжают работать даже когда `ANTHROPIC_API_KEY=disabled-not-used` (Sprint 1 T-1-006 — текущее состояние).
2. **AI-зависимые команды (`/agent`, текстовые сообщения)** деградируют gracefully: orchestrator пытается вызвать Anthropic, получает ошибку, возвращает понятное сообщение пользователю. Не падает.
3. **Pipeline notifications** — новый канал через `pipeline/telegram_notifier.py` (T-4-010), отдельный watcher. Не конфликтует со старыми командами.
4. **Перепиывание `/agent` под pipeline**: не имеет смысла. Семантика разная — `/agent` это "ответь от лица агента N", pipeline это "построй проект". Пользователь явно использует другие команды.

### Что НЕ меняется в `telegram_bot.py`

- Существующий код untouched. Все handlers, routing, message parsing — without changes.
- При полном `pip install -r requirements.txt` бот стартует, реагирует на команды.

### План на v2.0

После обкатки pipeline в production (3-6 месяцев) — повторно оценить:
- Если AI Команда не используется через Telegram — удалить `/agent`, текстовый routing
- Если используется — оставить как есть

---

## Действия в Sprint 5

| ID | Действие | Файл/директория | Тип |
|---|---|---|---|
| T-5-003 | НЕ ТРОГАТЬ telegram_bot.py — Вариант A | `ai_agency/telegram_bot.py` | no-op |
| T-5-004 | DEPRECATED.md в admin/ | `ai_agency/static/admin/DEPRECATED.md` | new file |
| T-5-005 | Решить судьбу shell-агентов | `01_AGENTS/`, `scripts/01..12_*.sh`, `launch_agents.sh` | оставить, добавить README |
| T-5-006 | Раздел про pipeline в `ai_agency/CLAUDE.md` | append section | edit |
| T-5-007 | Раздел про pipeline в `OWNER_GUIDE.md` | append section | edit |
| T-5-008 | Smoke test HQ страниц | manually open each | check |

## Что НЕ удаляется в Sprint 5

- `ai_agency/agents/` целиком — остаётся работать
- `ai_agency/orchestrator.py` — остаётся
- `ai_agency/scheduler.py` — остаётся
- `team.html`, `team-settings.html` — остаются (sidebar label "AI Команда (legacy)" уже обновлён в T-4-009)
- API endpoints `/api/task*`, `/api/agents/*` — остаются

Sprint 5 цель — **honest deprecation**, не cleanup. Удаление оставляем на v2.0.
