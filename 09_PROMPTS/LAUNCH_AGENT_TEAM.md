# Промпт запуска AI Delivery Agent Team

> Использование: WSL → tmux → окно claude → вставить этот промпт и отправить  
> Полная инструкция: 09_PROMPTS/WSL_LAUNCH_INSTRUCTION.md

---

## Быстрый старт (минимальный промпт)

Формат как в рабочем примере — максимум совместимости:

```markdown
ПРЯМО СЕЙЧАС создай и запусти Команду Агентов. Запусти ровно 3 агента ОДНОВРЕМЕННО.

Задачи:
1. Agent 1 (Researcher): 5 фактов об автоматизации МСБ 2025 → 03_RESEARCH/market/facts.txt
2. Agent 2 (Writer): черновик поста Telegram «ИИ-бот vs менеджер» → 02_CONTENT/telegram/drafts/draft.txt
3. Agent 3 (Designer): промпт Midjourney для картинки бизнес-автоматизации → 02_CONTENT/creative/image.txt

Контекст: CLAUDE.md, 00_MASTER/AGENCY_CONTEXT.md
ВАЖНО: TeamCreate → TaskCreate. Запуск СТРОГО ПАРАЛЛЕЛЬНО! Не жди никого.
```

---

## Основной промпт (скопируй и запусти)

```markdown
Твоя цель: Запустить AI Delivery Agent Team — маркетинговую команду агентства.

ПРЯМО СЕЙЧАС создай и запусти Команду Агентов (Agent Teams). Запусти ровно 3 агента ОДНОВРЕМЕННО.

Контекст команды: Прочитай CLAUDE.md, 00_MASTER/AGENCY_CONTEXT.md и 00_MASTER/TONE_OF_VOICE.md. Это агентство AI Delivery — цифровая автоматизация для МСБ (боты, MiniApp, n8n, сайты).

Задачи для команды (независимые, параллельные):

1. Agent 1 (Market Researcher): Исследуй 5 фактов об автоматизации МСБ в 2025 году. Разделяй ФАКТЫ и ГИПОТЕЗЫ. Сохрани в 03_RESEARCH/market/facts-msb-2025.txt

2. Agent 2 (Telegram Lead): Напиши черновик поста для Telegram-канала AI Delivery на тему «Почему ИИ-бот отвечает быстрее менеджера». CTA: бесплатный MVP. Сохрани в 02_CONTENT/telegram/drafts/draft-today.md

3. Agent 3 (Content Strategist): Напиши промпт для Midjourney/DALL·E для обложки поста про бизнес-автоматизацию (корпорация, технологии). Сохрани в 02_CONTENT/creative/image_prompt.txt

ВАЖНО: Задачи полностью независимые и должны стартовать СТРОГО ПАРАЛЛЕЛЬНО! Вызови инструмент TeamCreate, а затем TaskCreate. Не жди никого, запускай всех одновременно!
```

---

## Расширенный промпт (5 агентов)

```markdown
Твоя цель: Запустить AI Delivery Agent Team — полный контент-спринт.

ПРЯМО СЕЙЧАС создай и запусти Команду Агентов. Запусти ровно 5 агентов ОДНОВРЕМЕННО.

Контекст: Прочитай CLAUDE.md и 00_MASTER/*. Агентство AI Delivery — боты, MiniApp, n8n, сайты для МСБ.

Задачи (независимые, параллельные):

1. Market Researcher: 5 фактов об автоматизации МСБ 2025 → 03_RESEARCH/market/facts-msb-2025.txt
2. Telegram Lead: пост «ИИ-бот vs менеджер» → 02_CONTENT/telegram/drafts/draft-today.md
3. Threads Creator: 3 треда про автоматизацию заявок → 02_CONTENT/threads/drafts/threads-today.md
4. Content Strategist: контент-план на неделю (10 тем) → 02_CONTENT/content_plan_week.md
5. Competitor Analyst: топ-3 инсайта по конкурентам в нише «автоматизация» → 03_RESEARCH/competitors/insights-today.md

Запуск СТРОГО ПАРАЛЛЕЛЬНО! TeamCreate → TaskCreate. Не жди — стартуй всех сразу.
```

---

## Промпт «День команды» (Chief of Staff + 3 агента)

```markdown
Твоя цель: Провести оперативный день AI Delivery Team.

ШАГ 1: Ты — Chief of Staff. Прочитай CLAUDE.md, 00_MASTER/AGENCY_CONTEXT.md, 07_OPS/backlog/backlog.md. Сегодня [ДАТА]. Сформируй план дня в 07_OPS/daily_logs/[ДАТА].md

ШАГ 2: ПРЯМО СЕЙЧАС запусти 3 агентов ОДНОВРЕМЕННО:

1. Content Strategist: бриф на пост по теме из плана дня → 02_CONTENT/telegram/brief-today.md
2. Telegram Lead: напиши пост по брифу → 02_CONTENT/telegram/drafts/post-today.md
3. Market Researcher: weekly digest за текущую неделю → 03_RESEARCH/weekly_digest/week_[N].md

TeamCreate → TaskCreate. Запуск параллельный.
```

---

## Переменные для подстановки

| Переменная | Значение |
|------------|----------|
| `[ДАТА]` | `$(date +%Y-%m-%d)` |
| `[N]` | `$(date +%V)` (номер недели) |
| `today` | текущая дата в формате YYYY-MM-DD |

---

## После выполнения

- Chief of Staff: собрать результаты, обновить daily_log
- QA Agent: проверить созданные материалы (по запросу)
- Отчёт: `07_OPS/daily_logs/YYYY-MM-DD.md`
