# CLAUDE.md — AI Delivery HQ (операционное ядро агентства)

> Контекст для Claude. Читать в начале любой сессии, где задача касается кода `ai_agency/`.
> Цель: понять архитектуру за 5 минут и не сломать прод.

---

## 1. Что это

**AI Delivery HQ** — операционная система AI-агентства Никиты. Не «дашборд», а полноценный центр управления:

- **Бэкенд:** FastAPI + SQLite (`agency.db`)
- **Фронт:** статические HTML/CSS/JS в `static/hq/` (без сборщика, ванильный JS)
- **Telegram-бот:** `telegram_bot.py` (long polling)
- **Планировщик:** `scheduler.py` (asyncio + `schedule`)
- **Агенты:** 23 AI-агента на Anthropic SDK (`agents/team.py`)
- **Деплой:** systemd + nginx, сервер `89.22.235.144`, путь `/var/www/ai_agency/ai_agency/`

Запускается одним процессом через `python main.py`. Все компоненты живут в одном asyncio event-loop.

---

## 2. Ключевые правила (читать первыми)

1. **Не запускай долгие задачи в основном loop** без `asyncio.create_task` или `_run_optional_component` — это уронит API.
2. **Не пиши markdown в ответах агентов.** Telegram не рендерит `##`, `**`, `---`. В `agents/base.py` есть `AGENCY_FOOTER`, который явно это запрещает.
3. **Все агенты отвечают по-русски, без вводных «Конечно!», «Отличный вопрос!»** — это зашито в system prompts.
4. **Контекст агентства подгружается динамически** через `agency_context_loader.get_agency_context()`. Кэшируется на 60 секунд. Не дёргай файл напрямую — используй loader.
5. **БД миграции — без Alembic.** Всё через `CREATE TABLE IF NOT EXISTS` в `database.py` + ручные `ALTER TABLE` на старте. Если меняешь схему — добавляй именно так.
6. **`.env` на проде НЕ перезаписывать** через WinSCP без бэкапа. Там реальные ключи.
7. **При правке `api.py`/`hq_v3_api.py`** — после деплоя ОБЯЗАТЕЛЬНО `systemctl restart ai-agency` и Ctrl+F5 в браузере. Иначе старый код в кэше.

---

## 3. Стек и зависимости

```
Python 3.13
fastapi==0.110.0          # API
uvicorn==0.27.0           # ASGI-сервер
anthropic>=0.40.0,<1      # Claude SDK
python-telegram-bot==21.0 # Telegram-бот
aiosqlite==0.20.0         # асинхронный доступ к SQLite
schedule==1.2.0           # cron-like в Python
jinja2==3.1.3             # шаблоны (используются минимально)
pydantic>=2.10.0,<3       # схемы запросов/ответов
pypdf, python-docx, openpyxl  # парсинг загружаемых файлов в knowledge_base
```

**Важно:** `anthropic 0.25.x` ломается с `httpx 0.28+` — закреплены диапазоны.

Виртуалка: `venv/` (Windows-структура: `Scripts/`, не `bin/`). На сервере — отдельный venv, путь см. `install.sh`.

---

## 4. Структура файлов

```
ai_agency/
├── main.py                       # Точка входа: запускает API + бот + scheduler
├── api.py                        # ОСНОВНОЙ FastAPI (auth, tasks, content, clients, projects, students)
├── hq_v3_api.py                  # Дополнительные эндпоинты HQ v3 (CRM, delivery, executors, channel, notes)
├── orchestrator.py               # Координация агентов, режимы lite/standard/full, маршрутизация
├── database.py                   # Все CREATE TABLE, query helpers, форматирование отчётов
├── agency_context_loader.py      # Загрузка контекста агентства (uploaded → legacy → default + knowledge_base)
├── delivery_template_seed.py     # Сид-данные для шаблонов проектов в delivery
├── hq_snapshot.py                # Снапшоты состояния HQ
├── panel_settings.py             # Настройки панели (модели, режимы)
├── telegram_bot.py               # Telegram-бот (команды /report, /clients, /students, /finance, /agent)
├── scheduler.py                  # Дневной/недельный циклы (планировщик)
│
├── agents/
│   ├── base.py                   # AgentBase, AgentResponse — общий класс агента
│   ├── team.py                   # 23 конкретных агента (наследуют AgentBase)
│   ├── context.py                # Контекст для агентов
│   ├── request_context.py        # ContextVars для override модели в рамках запроса
│   └── __init__.py
│
├── static/hq/                    # Фронт панели HQ — ванильный HTML/JS/CSS
│   ├── index.html                # дашборд
│   ├── crm.html                  # CRM (клиенты, сделки)
│   ├── delivery.html             # Процесс доставки проектов
│   ├── analytics.html            # Метрики и аналитика
│   ├── tasks.html                # Задачи команды
│   ├── my-tasks.html             # Личные задачи
│   ├── team.html                 # Чат с агентами
│   ├── team-settings.html        # Настройки агентов
│   ├── executors.html            # Внешние исполнители
│   ├── knowledge.html            # База знаний (загрузка PDF/DOCX/XLSX)
│   ├── channel.html              # Контент-канал (Telegram/VC/Threads)
│   ├── account.html              # Профиль владельца
│   ├── notes.html                # Заметки
│   ├── review.html               # Ревью контента
│   ├── settings.html             # Системные настройки
│   ├── login.html
│   ├── _base.css, _components.js # общие стили и компоненты
│   └── hq-*.{css,js}             # темы и общая логика
│
├── static/site/                  # Маркетинговый лендинг (/service/)
├── static/admin/                 # Старая админка (deprecated)
│
├── data/
│   ├── agency_context.md         # Загруженный через панель контекст агентства (приоритет 1)
│   └── knowledge/                # Файлы knowledge_base (текстовые экстракты)
│
├── tests/
│   ├── e2e/                      # Playwright e2e
│   ├── playwright.config.js
│   └── run_tests.sh
├── _delivery_e2e_test.py         # Python e2e для delivery
├── _release_gate_test.py         # Гейт перед релизом
├── test_full.py                  # Полный тестовый прогон
│
├── tools/sprint5_verify.py       # Верификация спринта
├── backups/                      # Авто-бэкапы БД (формат agency_YYYYMMDD_HHMMSS_*.db)
│
├── agency.db                     # Главная БД (SQLite)
├── _test_p6.db                   # Тестовая БД
│
├── install.sh                    # Установка на сервер
├── setup_nginx.sh                # Настройка nginx
├── nginx_addition.conf           # Конфиг nginx для HQ
├── README_DEPLOY.md              # Развёрнутая инструкция по деплою
├── OWNER_GUIDE.md                # Краткая шпаргалка для владельца (Telegram-команды, перезапуск)
│
├── requirements.txt
├── .env / .env.example
└── venv/
```

---

## 5. Архитектура запуска (`main.py`)

```
asyncio.run(main())
    ├── check_env()              # Проверка ANTHROPIC_API_KEY и др.
    ├── init_db()                # CREATE TABLE IF NOT EXISTS + ALTER
    ├── Orchestrator()           # Загружает 23 агента
    │
    └── tasks = [
            start_api_server()           # uvicorn FastAPI на $HOST:$PORT (default 0.0.0.0:8000)
            start_telegram_bot()         # пропускается, если WEB_ONLY=true
            start_scheduler()            # пропускается, если WEB_ONLY=true
        ]
```

**Режим `WEB_ONLY=true`** (или `API_ONLY=true`) — только API+статика, без бота и планировщика. Используй локально, когда бот уже работает на сервере (чтобы не было конфликта polling-ов).

**Ошибки бота/планировщика не валят API** — оборачиваются в `_run_optional_component`.

---

## 6. Иерархия агентов (23 шт.)

```
Владелец (человек)
└── ChiefOfStaff [Управление]
      ├── ContentDirector [Контент]
      │     ├── TelegramWriter
      │     ├── ThreadsWriter
      │     ├── VCWriter
      │     └── QAEditor
      ├── ResearchHead [Аналитика]
      │     ├── MarketAnalyst
      │     ├── CompetitorAnalyst
      │     └── TrendAnalyst
      ├── ProductManagerAgent [Продукт]
      │     ├── OfferStrategist
      │     └── HypothesisAnalyst
      ├── WebsiteStrategist [Сайт]
      │     ├── CROAnalyst
      │     └── WebCopywriter
      ├── AI Solutions (для клиентов)
      │     ├── ClientCEO
      │     ├── AIStrategist
      │     ├── CrisisManager
      │     ├── SolutionsProductManager
      │     ├── KPWriter
      │     └── B2BSpecialist
      └── AccountManager [Операции] — клиенты, проекты, ученики, финансы
```

### Как добавить нового агента

1. Создай класс в `agents/team.py`:
   ```python
   class NewAgent(AgentBase):
       def __init__(self):
           super().__init__(
               name="new_agent",          # snake_case, уникальный
               role="Новый специалист",
               department="Отдел",
               reports_to="chief_of_staff",
               max_tokens=1200,
           )
       def build_system_prompt(self) -> str:
           return _ctx(self, """Ты — ...""")
   ```
2. Зарегистрируй в `Orchestrator.team` (см. `orchestrator.py`).
3. При необходимости — добавь его в маршрутизацию `_run_department` или новый метод.
4. Добавь UI-карточку в `team-settings.html` если нужен переключатель.

### Базовый контракт агента

- `think(task_input, context, task_id)` — основной метод. Возвращает `AgentResponse(text, tokens, success, error)`.
- `agency_context` — property, тянет актуальный контекст через `get_agency_context()` (кэш 60с).
- `_effective_model()` — выбирает модель: override из `panel_model_override` (ContextVar) → дефолт из `CLAUDE_MODEL`.
- Логирование выполнения — в БД, таблица `agent_executions`.

---

## 7. Режимы выполнения задач

В `orchestrator.py._resolve_task_mode`:

| Режим | Что делает | Когда использовать |
|---|---|---|
| `lite` | Один агент по задаче, без декомпозиции | Простые однострочные запросы, экономия токенов |
| `standard` | ChiefOfStaff декомпозирует → 1–3 агента | Дефолт, оптимальный баланс |
| `full` | Полная декомпозиция, все релевантные отделы | Сложные задачи (стратегия, лонгриды, исследования) |

Управление: `DEFAULT_TASK_MODE` в `.env` или override через `/api/panel/settings` (PUT).

---

## 8. База данных (`agency.db`)

Главные таблицы (см. `database.py`):

| Таблица | Что хранит |
|---|---|
| `app_settings` | Настройки панели (модели, режимы) |
| `tasks` | История задач, поставленных команде |
| `agent_executions` | Лог каждого вызова агента (tokens, время, успех) |
| `content` | Сгенерированный контент (статусы: draft → approved → published) |
| `reports`, `daily_reports` | Дневные/недельные отчёты |
| `backlog` | Бэклог идей |
| `clients` | CRM: клиенты |
| `projects`, `project_tasks` | Проекты клиентов и задачи внутри |
| `students`, `student_tasks` | Ученики инфопродукта |
| `delivery_projects`, `delivery_stages`, `delivery_tasks`, `delivery_checklist`, `delivery_comments`, `delivery_templates` | Процесс доставки проектов |
| `executors` | Внешние исполнители |
| `payments` | Платежи (клиентов и учеников) |
| `tasks_v2`, `tasks_v2_checklist`, `tasks_v2_comments` | Новая система задач |
| `ideas` | Банк идей |
| `owner_notes` | Заметки владельца |
| `channel_posts` | Посты для Telegram-канала |
| `hq_users` | Пользователи HQ (auth) |
| `hq_agent_messages` | История чатов с агентами в HQ |
| `metrics_cache` | Кэш метрик для дашборда |
| `reminders` | Напоминания |
| `knowledge_base` | Загруженные документы (PDF/DOCX/XLSX → text) |
| `timeline_events` | События в таймлайне |

**Конвенции:**
- `created_at`, `updated_at` — TEXT (ISO 8601), не DATETIME
- ID — INTEGER PRIMARY KEY AUTOINCREMENT
- Soft delete — через флаг `archived` или `deleted_at`, физическое удаление редко

**Бэкапы:** автоматически в `backups/` при старте приложения и через `/api/backup` (POST).

---

## 9. API эндпоинты (основное)

### Авторизация
- `POST /api/auth/login` — логин (email + password)
- `GET /api/auth/me` — текущий юзер
- `POST /api/auth/logout`
- Роли: `owner`, `pm`, `executor` — через `require_role(...)`

### Задачи и агенты
- `POST /api/task` — поставить задачу (вход в orchestrator)
- `GET /api/task/{id}` — статус задачи
- `GET /api/tasks` — список задач
- `GET /api/tasks/{id}/messages` — сообщения внутри задачи
- `WS /ws/task/{id}` — стриминг прогресса (WebSocket)

### CRM / Проекты / Ученики
- `GET/POST/PUT/DELETE /api/clients` (+ `{id}`)
- `GET/POST/PUT /api/projects` (+ `{id}/tasks`)
- `GET/POST/PUT /api/students` (+ `{id}/tasks`)

### Контент
- `GET /api/content` — список (фильтры по статусу, каналу)
- `POST /api/content/{id}/approve|reject|publish`

### Контекст агентства
- `GET /api/agency-context` — статус и метаданные
- `POST /api/agency-context/upload` — загрузка нового контекста (.md)
- `GET /api/agency-context/template` — скачать шаблон

### Метрики и сервис
- `GET /api/metrics` — сводные метрики
- `GET /api/hq/dashboard-summary` — дайджест для главной
- `GET /api/status` — состояние системы
- `POST /api/backup` — ручной бэкап БД

### Доп. эндпоинты v3 (`hq_v3_api.py`)
Покрывают: delivery, executors, notes, channel posts, ideas, payments, timeline.

**Auth:** legacy эндпоинты используют `Depends(verify_password)` (ADMIN_PASSWORD), новые — `require_role(...)` через сессии.

---

## 10. Telegram-бот (`telegram_bot.py`)

| Команда | Что делает |
|---|---|
| `/start` | Приветствие |
| `/report` | Отчёт дня (агрегат метрик, контент, задачи) |
| `/clients` | Статус клиентов |
| `/students` | Статус учеников |
| `/finance` | Финансовая сводка |
| `/deadlines` | Ближайшие дедлайны |
| `/agent [имя] [задача]` | Прямой чат с конкретным агентом |
| Любой текст | Маршрутизируется в `Orchestrator.run_task` (standard mode) |

**Только для `TELEGRAM_OWNER_ID`** — остальные сообщения игнорируются.

---

## 11. Frontend (HQ панель)

- **Без сборщика.** Ванильный HTML/JS, стили в `_base.css` + `hq-theme.css`.
- **Шаблон страницы:** есть `_patch_shell.py` — патчер, который вставляет общий хедер/нав в каждую `.html`. После правки HTML может потребоваться его перезапуск.
- **Общая логика:** `hq-global.js` (auth-check, навигация), `_components.js` (кнопки, модалки).
- **Мобильная версия:** `hq-mobile.{css,js}` — отдельные стили, активируются по media query.
- **Темы:** `hq-theme.css` — light/dark переключаются через CSS-переменные.

**Авторизация на фронте:** все запросы идут с куки сессии. Если 401 — редирект на `login.html`.

---

## 12. Переменные окружения (`.env`)

| Переменная | Что | Обязательность |
|---|---|---|
| `ANTHROPIC_API_KEY` | Ключ Claude API | **Критично** |
| `CLAUDE_MODEL` | Дефолтная модель (`claude-sonnet-4-6` сейчас) | Рекомендуется |
| `HQ_MODEL_ECONOMY` / `HQ_MODEL_QUALITY` | Пресеты эконом/качество | Опционально |
| `TELEGRAM_BOT_TOKEN` | Токен бота | Рекомендуется |
| `TELEGRAM_OWNER_ID` | ID владельца (для приватного бота) | Рекомендуется |
| `TELEGRAM_CHANNEL_ID` | Канал для автопостинга | Опционально |
| `HOST` / `PORT` | Где слушает FastAPI | Default: `0.0.0.0:8000` |
| `WEB_ONLY` | Не запускать бот и планировщик | `false` по умолчанию |
| `SECRET_KEY` | Секрет для сессий | Обязательно (есть default, но переопределить!) |
| `ADMIN_PASSWORD` | Пароль админки/legacy auth | Обязательно |
| `AUTO_PUBLISH` | Автопубликация контента в Telegram | `false` по умолчанию |
| `DAILY_POST_TIME` | Время дневного цикла | `09:00` |
| `TIMEZONE` | TZ планировщика | `Europe/Moscow` |
| `DEFAULT_TASK_MODE` | `lite` / `standard` / `full` | Default: `standard` |
| `YANDEX_METRIKA_TOKEN`, `YANDEX_METRIKA_COUNTER` | Метрика для аналитики | Опционально |

---

## 13. Деплой и эксплуатация

**Сервер:** `89.22.235.144`, путь `/var/www/ai_agency/ai_agency/`, systemd-юнит `ai-agency`.

**Стандартный деплой после правки кода:**
1. Загрузить файлы через WinSCP в `/var/www/ai_agency/ai_agency/`
2. `systemctl restart ai-agency`
3. `systemctl status ai-agency` — убедиться, что встал
4. `tail -f /var/log/ai-agency.log` — следить первые 30 секунд
5. Ctrl+F5 в браузере на `http://89.22.235.144/hq/`

**Откат:**
- БД — есть `backups/` (используй последний `*_startup.db`)
- Код — git в репе или предыдущая версия в WinSCP

**Логи:**
- `tail -f /var/log/ai-agency.log` — общий
- `tail -f /var/log/ai-agency-error.log` — только ошибки

**nginx:** `nginx_addition.conf` подключается к основному конфигу. После правки — `nginx -t && systemctl reload nginx`.

---

## 14. Тесты

- `tests/e2e/` — Playwright e2e тесты (запуск: `tests/run_tests.sh`)
- `_delivery_e2e_test.py` — Python e2e для модуля delivery
- `_release_gate_test.py` — гейт перед релизом, проверяет критичные пути
- `test_full.py` — полный прогон
- `tools/sprint5_verify.py` — верификация спринтов

**Перед коммитом крупных изменений:** `python _release_gate_test.py`.

---

## 15. Типичные грабли

1. **«Бот не отвечает»** → проверь `TELEGRAM_BOT_TOKEN` в `.env` + сетевой доступ к `api.telegram.org` (на VPS возможен таймаут — нужен VPN или WEB_ONLY локально).
2. **«HQ показывает старые данные»** → Ctrl+F5, бэкенд кэширует контекст агентства 60с (`agency_context_loader.CACHE_TTL`).
3. **«Database is locked»** → SQLite, не запускай две инстанции на одном `agency.db`. Используй WEB_ONLY локально.
4. **«ALTER TABLE падает на проде»** → старые БД могут не иметь новых колонок. Все миграции — в `init_db()` с try/except. Не вычищай таблицу — пересоздай через `CREATE TABLE clients_nocheck`-паттерн (есть в `database.py`).
5. **«Агент пишет markdown в Telegram»** → проверь, что `AGENCY_FOOTER` подключён в system prompt и max_tokens не урезает финальные инструкции.
6. **«Контекст не обновился»** → вызови `agency_context_loader.invalidate_cache()` или подожди 60с.
7. **«401 на API»** → сессия истекла. Re-login через `/api/auth/login` или проверь cookies.
8. **«Расходы по API растут»** → переключи `DEFAULT_TASK_MODE=lite` или `CLAUDE_MODEL=claude-3-5-haiku-20241022` в `.env`.

---

## 16. Когда я (Claude) работаю с этим кодом

**Перед любой правкой:**
1. Понять, какой слой трогаем: API (`api.py`/`hq_v3_api.py`), оркестрация (`orchestrator.py`), агенты (`agents/team.py`), БД (`database.py`), фронт (`static/hq/`).
2. Проверить, не сломаю ли существующий контракт API (фронт мог использовать).
3. Если меняем БД — ВСЕГДА `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` с try/except.
4. После правки — что нужно перезапустить (для бэка — `systemctl restart`, для фронта — Ctrl+F5).

**После правки — всегда упомянуть:**
- Какие файлы изменились
- Нужны ли миграции БД
- Нужен ли рестарт сервиса
- Какие тесты прогнать (`_release_gate_test.py` — минимум)

**Чего НЕ делаю без явной просьбы:**
- Не трогаю `.env` на сервере
- Не удаляю таблицы / колонки в БД
- Не удаляю файлы из `backups/`
- Не пушу в прод без локального теста (`WEB_ONLY=true python main.py`)

---

## 17. Связи с внешним миром

Этот код — часть большой папки `AI-запуск_обучение_инфопродукт/`. Корневой `CLAUDE.md` описывает контекст агентства целиком. Этот файл — только про код.

**Источники правды для контекста агентства:**
1. Загруженный через панель `data/agency_context.md` (приоритет 1)
2. `../00_MASTER/AGENCY_CONTEXT.md` + `TONE_OF_VOICE.md` + `OFFERS.md` (приоритет 2)
3. `../AGENCY_COPY_MASTER.md` (приоритет 3)
4. Дефолтный шаблон в `agency_context_loader.DEFAULT_CONTEXT` (fallback)

При расхождении — побеждает то, что выше по списку.

---

_Версия: 1.0 · Создано: 2026-05-03_
