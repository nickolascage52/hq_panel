# System Prompts агентов

Системные промпты агентов хранятся в **01_AGENTS/** — каждый агент в своей папке.

Здесь — быстрая навигация и справка.

## Назначение
- **Chief of Staff** — планирование, координация, отчёты
- **Content Strategist** — контент-план, брифи
- **Telegram Lead** — посты Telegram
- **Threads Creator** — посты и треды Threads
- **VC Writer** — статьи VC.ru и Дзен
- **Market Researcher** — исследования рынка
- **Competitor Analyst** — анализ конкурентов
- **Product Manager** — продуктовая линейка
- **Website Strategist** — стратегия сайта
- **CRO/UX Analyst** — конверсия и UX
- **Web Copywriter** — тексты сайта
- **QA Agent** — контроль качества

## Как использовать
При вызове агента передавайте соответствующий SYSTEM_PROMPT.md как контекст:

```
Прочитай 01_AGENTS/telegram_lead/SYSTEM_PROMPT.md и CLAUDE.md.
Напиши пост на тему: [тема]
```

Все агенты также читают CLAUDE.md и файлы из 00_MASTER/.
