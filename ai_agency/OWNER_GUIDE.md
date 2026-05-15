# AI Delivery HQ — Рабочий кабинет

## Доступ

- Панель: http://89.22.235.144/hq/
- Пароль: из ADMIN_PASSWORD в .env
- Telegram бот: @твой_бот

## Быстрые команды Telegram

| Команда | Что делает |
|---------|------------|
| /report | Отчёт дня |
| /clients | Статус клиентов |
| /students | Статус учеников |
| /finance | Финансы |
| /deadlines | Дедлайны |
| /agent [имя] [задача] | Прямой чат с агентом |

## Если что-то не работает

### Перезапустить систему

Подключись через PuTTY к 89.22.235.144

```bash
systemctl restart ai-agency
systemctl status ai-agency
```

### Посмотреть логи

```bash
tail -f /var/log/ai-agency.log
tail -f /var/log/ai-agency-error.log
```

### Обновить файлы после изменений в Cursor

1. Загрузи через WinSCP в /var/www/ai_agency/ai_agency/
2. `systemctl restart ai-agency`
3. Обнови страницу в браузере (Ctrl+F5)

## Настройки (.env файл)

Путь на сервере: /var/www/ai_agency/ai_agency/.env

Ключевые параметры:

- ANTHROPIC_API_KEY — ключ Claude API
- TELEGRAM_BOT_TOKEN — токен бота
- ADMIN_PASSWORD — пароль панели
- CLAUDE_MODEL — модель (claude-haiku-4-5-20251001 = дёшево)
- DEFAULT_TASK_MODE — lite / standard / full
- YANDEX_METRIKA_TOKEN — после подключения метрики
- YANDEX_METRIKA_COUNTER — номер счётчика

## Стоимость использования

- Claude Haiku: ~$0.001 за 1000 токенов
- Средняя задача в lite: ~$0.02-0.05
- Средняя задача в standard: ~$0.05-0.15
- $5 на балансе = ~50-100 полных задач в standard режиме

## 21 агент команды

**Управление:** Chief of Staff

**Контент:** Content Director, TG Writer, Threads Writer, VC Writer, QA Editor

**Аналитика:** Research Head, Market Analyst, Competitor Analyst, Trend Analyst

**Продукт:** Product Manager, Offer Strategist, Hypothesis Analyst

**Сайт:** Website Strategist, CRO Analyst, Web Copywriter

**Операции:** Account Manager

**AI Solutions:** Client CEO, AI Strategist, Crisis Manager, Solutions PM, KP Writer

---

## AI Pipeline (новое в v1.0, Sprint 2-4)

Автономная разработка клиентских проектов через Claude Code multi-agent. Работает параллельно со старой AI Командой (она помечена как `legacy` в sidebar).

### Запуск нового pipeline-проекта

1. Открыть HQ → пункт сайдбара **🤖 AI Pipeline**
2. Кнопка **+ Новый pipeline-run**
3. Заполнить форму:
   - **Название проекта** — короткое, например «Лендинг для Х»
   - **Описание идеи** — что нужно сделать (1-3 абзаца). Чем подробнее — тем меньше Claude доуточняет
   - **Тип проекта** — `landing` / `telegram_bot` / `n8n` / `ai_assistant` / `custom` (в v1.0 рабочий — только `landing`)
   - **Уровень автономии:**
     - `1` — спрашивает на каждом этапе (для критических проектов)
     - `2` — пауза только после Phase 4 (план спринтов) — **рекомендуется**
     - `3` — без остановок до конца
   - **Стратегия деплоя** — `none` / `vercel` / `aeza-subdomain` (в v1.0 работает только `none`, остальные — backlog v1.1)
4. Нажать **Запустить** → откроется detail-страница с прогрессом

### Как смотреть прогресс

- HQ → AI Pipeline → клик по карточке = детальная страница
- Header: статус + phase pills (1-7) + progress bar
- Tab **Overview** — текущая фаза + последние события
- Tab **Events** — полная лента в реальном времени (через WebSocket)
- Telegram приходят уведомления:
  - 🚀 Pipeline #N стартовал
  - 🔔 Pipeline #N: нужно одобрение (sprints) — для autonomy<3
  - 🎉 Pipeline #N готов к review — финал

### Когда нужно одобрить (autonomy_level<3)

После Phase 3 (Architecture, при autonomy=1 или 2) или Phase 4 (Sprints, при autonomy=1) — pipeline останавливается:
- Telegram: «🔔 нужно одобрение»
- HQ → run-detail → кнопка **Approve** активна
- Кликнуть → продолжается дальше

### Что НЕ работает в v1.0

- **Phase 5 (Sprint Execution)** — в v1.0 stub: per-sprint sleep + status update. Реальный spawn architect/builders/validator — backlog v1.1 когда `ANTHROPIC_API_KEY` восстановят.
- **Phase 6 (Validation)** — stub (нет real `npm build` / `pytest`).
- **Vercel/Aeza deploy** — stubs.
- **Pause/Resume/Abort кнопки** — disabled с подсказкой `v1.1`.
- **AI-чат с агентами в team.html (legacy)** — работает по-старому, но возвращает ошибку Anthropic если `ANTHROPIC_API_KEY=disabled-not-used` (намеренно отозван в Sprint 1).

### Когда упёрся в rate limit

Если Claude недельный лимит исчерпан, pipeline:
- Ставится на паузу (`status='paused_rate_limit'`)
- В DB сохраняется `resume_after` — время когда лимит обновится
- При рестарте сервиса (или раз в N сек, см. `pipeline.resume_pending_runs`) — auto-resume если `resume_after <= now`
- Telegram: «🔋 Pipeline #N упёрся в rate limit»

В v1.0 RateLimitManager парсит лимиты через `pipeline_rate_limits` таблицу. Live `claude /usage` парсинг — backlog v1.1.

### Где смотреть логи pipeline

- В БД: `pipeline_events` (через UI Events tab или прямо `sqlite3 agency.db`)
- В системе: `tail -f /var/log/ai-agency.log | grep -i pipeline`
- Для конкретного run-а: workspace в `pipeline_workspaces/<id>/`:
  - `docs/prompt.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`
  - `docs/sprints/sprint-N-*.md`
  - `docs/final-report.md` (после Phase 7)
  - `.git/` — отдельный repo, можно смотреть `git log` в этой папке

### API напрямую (опционально)

```bash
# Создать run
curl -X POST http://89.22.235.144/api/pipeline/runs \
  -H "X-Auth-Token: <ваш токен из HQ>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","raw_idea":"...","project_type":"landing","autonomy_level":2,"deploy_strategy":"none"}'

# Получить детали
curl http://89.22.235.144/api/pipeline/runs/1 -H "X-Auth-Token: ..."

# События
curl http://89.22.235.144/api/pipeline/runs/1/events?limit=50 -H "X-Auth-Token: ..."

# Approve
curl -X POST http://89.22.235.144/api/pipeline/runs/1/approve -H "X-Auth-Token: ..."
```

### Activate Claude skills (один раз, для full Phase 1-4 работы)

Pipeline phases используют скилы. Скопировать templates из репо в пользовательский каталог:

```powershell
# Windows
$skills = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path "$skills\prd-builder","$skills\architecture-decider","$skills\sprint-planner" | Out-Null
Copy-Item "agency\standards\skills\prd-builder.md"        "$skills\prd-builder\SKILL.md"
Copy-Item "agency\standards\skills\architecture-decider.md" "$skills\architecture-decider\SKILL.md"
Copy-Item "agency\standards\skills\sprint-planner.md"     "$skills\sprint-planner\SKILL.md"
```

После этого Claude Code будет находить `/prd-builder`, `/architecture-decider`, `/sprint-planner` при invocation из pipeline-фаз.
