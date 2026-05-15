# Agency Standard: Telegram Bot

**Version:** 1.0
**Last updated:** 2026-05-16

This document defines how Telegram bots are built in this agency. Any AI agent
generating a Telegram bot project MUST follow these standards.

## Stack (LOCKED)

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Language | Python | 3.11+ | typing required, no `Any` in public API |
| Framework | aiogram | 3.x | Async-first, FSM out of the box |
| Storage | SQLite via aiosqlite | latest | Postgres only if owner explicitly asks |
| Config | python-dotenv | 1.0+ | All secrets in `.env` |
| HTTP client | httpx | 0.27+ | for API calls (no requests sync lib) |
| Background tasks | asyncio + APScheduler | 3.x (if cron-like needed) | Otherwise raw asyncio |
| Deployment | systemd (Linux) | — | Single-binary-style, see install.sh template |
| Monitoring | logging + Sentry (opt) | — | Sentry only if budget |

## Folder structure

```
project-root/
├── bot/
│   ├── __init__.py
│   ├── main.py                    # entry point: dp.start_polling()
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py               # /start, /help
│   │   ├── menu.py                # main keyboard navigation
│   │   ├── <feature>.py           # one file per top-level feature
│   │   └── admin.py               # admin-only handlers
│   ├── states/                    # FSM states (one file per flow)
│   │   └── *.py
│   ├── keyboards/                 # InlineKeyboardMarkup builders
│   │   └── *.py
│   ├── middlewares/               # auth, throttling, etc.
│   │   └── *.py
│   ├── services/                  # business logic, no aiogram imports here
│   │   └── *.py
│   └── db/                        # aiosqlite queries
│       ├── schema.py
│       └── *.py
├── tests/
│   ├── conftest.py
│   └── test_*.py
├── scripts/
│   ├── install.sh                 # systemd setup
│   └── run.sh
├── .env.example
├── requirements.txt
└── README.md
```

## Conventions

1. **Async everywhere.** No `time.sleep`, no `requests`, no sync DB drivers.
2. **Handler = one function per command/callback.** Long flows → FSM in `states/`.
3. **Keyboards as builders.** Don't construct `InlineKeyboardMarkup` inline in handlers — build in `keyboards/<feature>.py`.
4. **Services don't import aiogram.** Handler calls service, service does the work, returns plain data.
5. **All texts** centralized in `bot/texts.py` or `bot/strings.py` (Russian by default for Russian projects).
6. **Errors** logged + user-friendly message back to user (`Произошла ошибка, попробуйте позже`).
7. **No long-running ops in handler context** — push to background task with status updates.

## Performance budget

- Cold start: < 3 sec to start polling
- Handler response: < 200ms median for DB-only, < 1 sec with API calls
- Memory: < 100 MB resident for typical bot

## Что НЕ использовать

- `python-telegram-bot` (другая школа, тяжелее API)
- `pyTelegramBotAPI` (sync, устарел)
- Чистый `requests`-based polling (нет async)
- Webhook без HTTPS — только если за nginx с SSL
- `pickle` для FSM storage (используем aiosqlite или RedisStorage)

## Security

- `.env` всегда gitignored
- Bot token проверять через `getMe` при старте — fail-fast если нет access
- Admin handlers — middleware с `tg_user_id IN (set)` проверкой
- Rate limit на user — `aiogram.middlewares.ThrottlingMiddleware` или custom
- Никогда не логировать сообщения пользователей в чистом виде (PII)

## Deployment template

```ini
# /etc/systemd/system/<bot-name>.service
[Unit]
Description=<Bot Name> Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/<bot-name>
Environment="PYTHONUNBUFFERED=1"
ExecStart=/var/www/<bot-name>/venv/bin/python -m bot.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/<bot-name>.log
StandardError=append:/var/log/<bot-name>-error.log

[Install]
WantedBy=multi-user.target
```

## Telegram-specific gotchas

- `parse_mode` ставить **в DefaultBotProperties** на уровне `Bot()`, не в каждом send
- Длинные сообщения (>4096 chars) — резать на части (`bot/utils/long_text.py` helper)
- Inline buttons callback_data ≤ 64 байт — длинные данные → DB row + ID в callback_data
- `bot.delete_webhook()` перед `start_polling()` если когда-то была регистрация webhook
- В Long-polling: `drop_pending_updates=True` чтобы не получать накопленный спам после рестарта
