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
