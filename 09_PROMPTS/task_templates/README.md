# Шаблоны задач

Библиотека типовых формулировок задач для агентов.

## Где искать
- **09_PROMPTS/examples/example_tasks.md** — полная библиотека примеров запросов по каждому агенту
- **08_WORKFLOWS/templates/** — шаблоны брифов и Research Brief

## Быстрые промпты

### Chief of Staff — план дня
```
Прочитай CLAUDE.md, 00_MASTER/AGENCY_CONTEXT.md и 07_OPS/backlog/backlog.md.
Сегодня [ДАТА]. Сформируй план дня.
Определи топ-3 задачи, нужных агентов и ожидаемые артефакты.
Запиши в 07_OPS/daily_logs/[ДАТА].md
```

### Telegram Lead — пост
```
Прочитай 00_MASTER/TONE_OF_VOICE.md.
Напиши пост для Telegram на тему: [ТЕМА]
Рубрика: [рубрика]. CTA: [действие].
Максимум 1500 символов.
Сохрани в 02_CONTENT/telegram/drafts/[ДАТА].md
```

### Content Strategist — контент-план
```
Прочитай 00_MASTER/OFFERS.md и 00_MASTER/TONE_OF_VOICE.md.
Создай контент-план на [МЕСЯЦ]:
- 30 тем для Telegram (по рубрикам)
- 30 тем для Threads
- 2 темы для VC
Сохрани в 02_CONTENT/content_plan_[месяц].md
```

### Agent Teams — недельный спринт
```
Создай команду для недельного контент-спринта:
- Content Strategist: план на неделю
- Telegram Lead: 5 постов по плану
- Threads Creator: 5 тредов по плану
- QA Agent: проверка всех материалов
Сохрани в 02_CONTENT/. Сгенерируй REPORT.md.
```
