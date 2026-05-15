# Pixel Agents - AI Growth Team

## Как запустить агентов в Pixel Agents

### Способ 1: Через кнопку "+ Agent"

1. Откройте панель **Pixel Agents** в VS Code
2. Нажмите кнопку **"+ Agent"**
3. В открывшемся терминале выполните один из скриптов:

```bash
bash scripts/01_chief_of_staff.sh
```

4. Повторите для каждого агента

### Способ 2: Вручную в терминале

Откройте новый терминал и запустите:

```bash
claude --print "Ты Chief of Staff. Прочитай 01_AGENTS/chief_of_staff/SYSTEM_PROMPT.md"
```

---

## Список агентов

| # | Скрипт | Агент | Роль |
|---|--------|-------|------|
| 1 | `01_chief_of_staff.sh` | Chief of Staff | Координатор команды |
| 2 | `02_content_strategist.sh` | Content Strategist | Контент-стратегия |
| 3 | `03_telegram_lead.sh` | Telegram Lead | Посты для Telegram |
| 4 | `04_threads_creator.sh` | Threads Creator | Контент для Threads |
| 5 | `05_vc_writer.sh` | VC Writer | Статьи VC.ru/Дзен |
| 6 | `06_product_manager.sh` | Product Manager | Продуктовая линейка |
| 7 | `07_market_researcher.sh` | Market Researcher | Исследование рынка |
| 8 | `08_competitor_analyst.sh` | Competitor Analyst | Анализ конкурентов |
| 9 | `09_cro_ux.sh` | CRO/UX Analyst | Конверсия и UX |
| 10 | `10_web_copywriter.sh` | Web Copywriter | Тексты для сайта |
| 11 | `11_website_strategist.sh` | Website Strategist | Стратегия сайта |
| 12 | `12_qa_agent.sh` | QA Agent | Контроль качества |

---

## Рекомендуемый порядок запуска

1. **Chief of Staff** — главный координатор
2. **Content Strategist** — планирует контент
3. **Контент-агенты** (Telegram, Threads, VC) — создают материалы
4. **Research-агенты** (Market, Competitor) — исследования
5. **Website-агенты** (Strategist, Copywriter, CRO) — работа с сайтом
6. **QA Agent** — проверка всех выходов
