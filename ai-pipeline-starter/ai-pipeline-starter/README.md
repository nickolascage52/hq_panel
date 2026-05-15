# AI Pipeline Starter Pack для AI Delivery HQ

Этот стартовый пакет создан под **конкретный проект AI_Delivery_Team** на основе аудита от 2026-05-15.

Цель проекта: построить модуль автономной разработки клиентских проектов через Claude Code, который **заменит** старую AI Команду (23 prompt-агента) и интегрируется внутрь существующей HQ-панели.

## Что внутри

```
ai-pipeline-starter/
├── README.md                       # этот файл
├── docs/
│   ├── PRD.md                      # бизнес-требования, что и зачем строим
│   ├── ARCHITECTURE.md             # технические решения, как строим
│   └── sprints/
│       ├── _index.md               # обзор всех 5 спринтов
│       ├── sprint-1-foundation.md  # git, секреты, sessions в БД (БЛОКЕРЫ)
│       ├── sprint-2-pipeline-skeleton.md
│       ├── sprint-3-claude-code-integration.md
│       ├── sprint-4-ui-and-hq-integration.md
│       └── sprint-5-cleanup-and-handoff.md
├── CLAUDE.md                       # правила для агентов проекта
├── agency/
│   └── standards/
│       └── landing.md              # первый стандарт агентства (для тестового проекта)
├── .claude/
│   └── agents/
│       ├── orchestrator.md
│       ├── architect.md
│       ├── builder-fastapi.md
│       ├── builder-vanilla-frontend.md
│       ├── validator.md
│       ├── code-reviewer.md
│       └── prd-compliance-checker.md
└── pipeline_module_seed/
    ├── pipeline_README.md          # как будет выглядеть pipeline/ модуль внутри ai_agency/
    └── pipeline_sql_seed.sql       # черновик новых таблиц БД
```

## Как пользоваться

### Шаг 1. Распаковать содержимое поверх существующего AI_Delivery_Team

**ВАЖНО:** распаковка **не перезапишет** твои файлы. Все новые файлы либо в новых папках (`docs/`, `agency/`, `.claude/`), либо имеют уникальные имена.

```bash
cd /path/to/AI_Delivery_Team
# Распакуй сюда содержимое этого zip
```

После распаковки структура AI_Delivery_Team будет такая:

```
AI_Delivery_Team/
├── (всё что было раньше)
├── docs/                          # ← НОВОЕ: PRD, ARCHITECTURE, sprints
├── agency/                        # ← НОВОЕ: standards
├── .claude/                       # ← ОБНОВИТСЯ: добавятся agents/
├── pipeline_module_seed/          # ← НОВОЕ: шаблон для будущего pipeline/ модуля
└── README_PIPELINE.md             # ← см. где этот файл
```

### Шаг 2. Прочитать всё по порядку

1. `docs/PRD.md` — что мы строим и зачем
2. `docs/ARCHITECTURE.md` — как мы это строим технически
3. `docs/sprints/_index.md` — обзор работы на 5 спринтов
4. `docs/sprints/sprint-1-foundation.md` — что делаем прямо сейчас

### Шаг 3. Открыть проект в VS Code + Claude Code

```bash
cd AI_Delivery_Team
code .
```

В VS Code открой Claude Code (Ctrl+Esc).

### Шаг 4. Запустить Sprint 1

В Claude Code:

```
Read CLAUDE.md, docs/PRD.md, docs/ARCHITECTURE.md, docs/sprints/sprint-1-foundation.md.

Затем используй Plan Mode (Shift+Tab дважды) и составь план исполнения Sprint 1. Покажи мне план, дождись моего "go" и только после этого начинай выполнять задачи.

ВАЖНО: Sprint 1 это инфраструктурный спринт — git, секреты, hq_sessions в БД. Никакой логики pipeline ещё не пишем.
```

После одобрения плана — Claude Code пойдёт по задачам Sprint 1.

### Шаг 5. После каждого спринта

1. Прочитай `/docs/overseer-log.md` (создаётся в ходе спринта)
2. Проверь git log
3. Запусти e2e-тесты вручную: `python _release_gate_test.py`
4. Если всё ок — переходи к следующему спринту

## Принципы работы

- **Не запускать всё разом.** Sprint 1 → проверка → Sprint 2 → проверка ...
- **Git after every task.** Каждая закрытая задача = коммит с тегом `[T-N-XXX]`.
- **Старую AI Команду НЕ трогаем** до Sprint 5. Она работает параллельно.
- **Telegram-бот тоже не трогаем** до Sprint 5 — он зависит от старого orchestrator'а.
- **Если что-то не ясно или плохо специфицировано** — стоп, спроси меня в чате claude.ai.

## Контакты с памятью

В чате claude.ai (где составлялся этот пакет) сохранён контекст:
- Архитектура HQ
- План интеграции
- Прошлые решения
- Этот пакет

Если нужна помощь — напиши в claude.ai «продолжаем pipeline, sprint N, вопрос такой-то».

---

**Готовность кодовой базы к интеграции: 6/10** (из аудита).
**Прогноз времени:** 5 спринтов × 2-4 дня каждый = ~2-3 недели при 2-3 часах в день.

Удачи. Поехали.
