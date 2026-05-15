#!/bin/bash
# Генерация REPORT.md после цикла работы

DATE=$(date +%Y-%m-%d)
WEEK=$(date +%V)
# Рабочая директория: корень проекта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPORT="$WORKDIR/REPORT.md"

echo "=== ГЕНЕРАЦИЯ ОТЧЁТА: $DATE ==="

# Считаем артефакты
TELEGRAM_COUNT=$(ls "$WORKDIR/02_CONTENT/telegram/drafts/" 2>/dev/null | wc -l)
VC_COUNT=$(ls "$WORKDIR/02_CONTENT/vc/drafts/" 2>/dev/null | wc -l)
RESEARCH_COUNT=$(ls "$WORKDIR/03_RESEARCH/market/" 2>/dev/null | wc -l)

cat > "$REPORT" << EOF
# 📊 ОТЧЁТ РАБОТЫ AI GROWTH КОМАНДЫ
**Дата генерации:** $DATE
**Неделя:** $WEEK

---

## 🎯 СТАТУС КОМАНДЫ

Все 12 агентов инициализированы и готовы к работе.

---

## 📁 АРТЕФАКТЫ

| Направление | Файлов создано |
|---|---|
| Telegram черновики | $TELEGRAM_COUNT |
| VC статьи | $VC_COUNT |
| Исследования | $RESEARCH_COUNT |

---

## 📋 СОСТОЯНИЕ BACKLOG

### Высокий приоритет
$(grep "- \[ \]" "$WORKDIR/07_OPS/backlog/backlog.md" | head -5 | sed 's/^/- /')

---

## 🤖 СОСТАВ КОМАНДЫ

| # | Агент | Статус | System Prompt |
|---|---|---|---|
| 1 | Chief of Staff | ✅ Готов | 01_AGENTS/chief_of_staff/ |
| 2 | Content Strategist | ✅ Готов | 01_AGENTS/content_strategist/ |
| 3 | Telegram Lead | ✅ Готов | 01_AGENTS/telegram_lead/ |
| 4 | Threads Creator | ✅ Готов | 01_AGENTS/threads_creator/ |
| 5 | VC Writer | ✅ Готов | 01_AGENTS/vc_writer/ |
| 6 | Product Manager | ✅ Готов | 01_AGENTS/product_manager/ |
| 7 | Market Researcher | ✅ Готов | 01_AGENTS/market_researcher/ |
| 8 | Competitor Analyst | ✅ Готов | 01_AGENTS/competitor_analyst/ |
| 9 | Website Strategist | ✅ Готов | 01_AGENTS/website_strategist/ |
| 10 | CRO/UX Analyst | ✅ Готов | 01_AGENTS/cro_ux/ |
| 11 | Web Copywriter | ✅ Готов | 01_AGENTS/web_copywriter/ |
| 12 | QA Agent | ✅ Готов | 01_AGENTS/qa_agent/ |

---

## 📂 СТРУКТУРА ПРОЕКТА

\`\`\`
~/ai_agency_team/
├── CLAUDE.md              ← читают все агенты
├── REPORT.md              ← этот файл
├── 00_MASTER/             ← знания агентства
├── 01_AGENTS/             ← system prompts (12 агентов)
├── 02_CONTENT/            ← контент по каналам
├── 03_RESEARCH/           ← исследования
├── 04_PRODUCT/            ← продуктовая работа
├── 05_WEBSITE/            ← сайт
├── 06_KNOWLEDGE_BASE/     ← кейсы, FAQ, возражения
├── 07_OPS/                ← операционка и отчёты
├── 08_WORKFLOWS/          ← пайплайны и чеклисты
├── 09_PROMPTS/            ← промпты и шаблоны
└── 10_TMUX/               ← скрипты для tmux
\`\`\`

---

## 🚀 БЫСТРЫЙ СТАРТ

### Шаг 1: Настройка (10 минут)
\`\`\`bash
cd ~/ai_agency_team
# Заполните реальными данными:
nano 00_MASTER/AGENCY_CONTEXT.md
nano 00_MASTER/OFFERS.md
\`\`\`

### Шаг 2: Запуск tmux сессии
\`\`\`bash
bash 10_TMUX/scripts/start_team.sh
\`\`\`

### Шаг 3: Запуск Claude Code
\`\`\`bash
# В окне 'claude' tmux сессии:
claude
# Для Agent Teams нужен Claude Max план (\$100-200/мес)
\`\`\`

### Шаг 4: Первый запрос (вставить в Claude Code)
\`\`\`
Прочитай CLAUDE.md и все файлы в 00_MASTER/.
Ты — Chief of Staff.
Сегодня $DATE.
Сформируй план дня:
1. Один пост для Telegram (тему подбери сам из OFFERS.md)
2. Подбери тему для исследования рынка
3. Дай 3 рекомендации по улучшению продуктового каталога
Запиши план в 07_OPS/daily_logs/$DATE.md
\`\`\`

### Шаг 5: Agent Teams (для параллельной работы)
\`\`\`
Создай команду агентов для выполнения недельного контент-плана:
- Content Strategist: составь план на неделю (7 постов Telegram + 7 Threads)
- Telegram Lead: напиши первые 3 поста по плану
- Threads Creator: напиши первые 3 треда по плану
- QA Agent: проверь все созданные материалы
Сохрани всё в соответствующие папки 02_CONTENT/
Сгенерируй REPORT.md по итогу работы.
\`\`\`

---

## ⚙️ КОНФИГУРАЦИЯ AGENT TEAMS

Файл: .claude/settings.json
\`\`\`json
{
  "experimental": {
    "agent_teams": true
  }
}
\`\`\`

Для активации Agent Teams нужен:
- Claude Max план (\$100-200/мес) или
- Claude Pro с доступом к Opus 4.6

---

## 📌 ВАЖНЫЕ КОМАНДЫ

\`\`\`bash
# Запуск ежедневного цикла
bash ~/ai_agency_team/10_TMUX/scripts/daily_cycle.sh

# Генерация отчёта
bash ~/ai_agency_team/10_TMUX/scripts/generate_report.sh

# Подключиться к tmux сессии
tmux attach -t ai_agency

# Показать все окна сессии
tmux list-windows -t ai_agency

# Переключение между окнами: Ctrl+B, затем номер окна (0-5)
\`\`\`

---

## 📖 ФАЙЛЫ КОТОРЫЕ НУЖНО ЗАПОЛНИТЬ

**ОБЯЗАТЕЛЬНО перед стартом:**
- [ ] 00_MASTER/AGENCY_CONTEXT.md — название, услуги, кейсы, каналы
- [ ] 00_MASTER/OFFERS.md — реальные услуги с ценами
- [ ] 06_KNOWLEDGE_BASE/cases/ — реальные кейсы клиентов

**ЖЕЛАТЕЛЬНО:**
- [ ] 06_KNOWLEDGE_BASE/objections.md — реальные возражения клиентов
- [ ] 06_KNOWLEDGE_BASE/faq.md — частые вопросы

---

*Отчёт сгенерирован автоматически: $DATE*
EOF

echo "✅ REPORT.md создан: $REPORT"
echo ""
cat "$REPORT"
