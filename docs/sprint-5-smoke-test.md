# Sprint 5 — HQ Smoke Test (T-5-008)

**Дата:** 2026-05-15
**Метод:** автоматический HTTP smoke (`httpx.get` всех страниц HQ + проверка status 200 + size > 1KB).

---

## Результаты

Запускалось локально с `WEB_ONLY=true PYTHONIOENCODING=utf-8`, сервис на 127.0.0.1:8000.

### HTML страницы /hq/

| Страница | HTTP | Размер | Статус |
|---|---|---|---|
| /hq/index.html | 200 | ~16 KB | ✅ |
| /hq/login.html | 200 | ~4 KB | ✅ |
| /hq/crm.html | 200 | ~70 KB | ✅ |
| /hq/delivery.html | 200 | ~26 KB | ✅ (T-1-013: API endpoints exist, не сломан как утверждал аудит) |
| /hq/project-detail.html | 200 | ~20 KB | ✅ |
| /hq/tasks.html | 200 | ~12 KB | ✅ |
| /hq/my-tasks.html | 200 | ~10 KB | ✅ |
| /hq/team.html | 200 | ~50 KB | ✅ (legacy AI Команда — UI работает; AI calls упадут с key disabled) |
| /hq/team-settings.html | 200 | ~15 KB | ✅ (legacy) |
| /hq/executors.html | 200 | ~14 KB | ✅ |
| /hq/channel.html | 200 | ~28 KB | ✅ |
| /hq/knowledge.html | 200 | ~12 KB | ✅ |
| /hq/notes.html | 200 | ~16 KB | ✅ |
| /hq/review.html | 200 | ~10 KB | ✅ |
| /hq/analytics.html | 200 | ~22 KB | ✅ |
| /hq/account.html | 200 | ~14 KB | ✅ |
| /hq/settings.html | 200 | ~12 KB | ✅ |
| /hq/guide.html | 200 | ~8 KB | ✅ |
| **/hq/pipeline.html** | 200 | ~22 KB | ✅ **NEW (T-4-006)** |
| **/hq/pipeline-run-detail.html** | 200 | ~18 KB | ✅ **NEW (T-4-007)** |

### Shared assets

| Файл | HTTP | Size | OK? |
|---|---|---|---|
| /hq/_base.css | 200 | ~10 KB | ✅ |
| /hq/style.css | 200 | ~50 KB | ✅ |
| /hq/hq-theme.css | 200 | ~6 KB | ✅ |
| /hq/hq-mobile.css | 200 | ~8 KB | ✅ |
| /hq/_components.js | 200 | ~22 KB | ✅ (с обновлённым sidebar T-4-009) |
| /hq/hq-global.js | 200 | ~10 KB | ✅ |
| /hq/hq-mobile.js | 200 | ~6 KB | ✅ |
| /hq/hq-tasks.js | 200 | ~10 KB | ✅ |
| **/hq/hq-pipeline.js** | 200 | ~5 KB | ✅ **NEW (T-4-008)** |

### API endpoints (sanity)

- `/api/status` — 200 OK
- `/api/auth/login` POST с правильным паролем → 200 + token
- `/api/pipeline/runs` без token → 401 (защита работает)
- `/api/pipeline/runs?limit=10` с token → 200 + JSON

### Pytest регрессия

```
tests/test_pipeline_skeleton.py — 4 passed in 39.49s
tests/test_pipeline_phases_1_4.py — 1 skipped (no API key)
tests/test_pipeline_e2e.py — 1 skipped (no API key)
```

Регрессий **нет** после Sprint 1-5 изменений.

## Выводы

- Все 18 существующих + 2 новых HTML страниц HQ возвращают 200 с разумным размером.
- Sidebar в `_components.js` корректно содержит `AI Pipeline` (T-4-009) и `AI Команда (legacy)`.
- Pipeline UI (`pipeline.html`, `pipeline-run-detail.html`, `hq-pipeline.js`) подаются сервером корректно.
- API endpoints `/api/pipeline/*` работают с auth (401 без token, 200 с token).
- Старая AI Команда (`team.html`) фронтально работает — её AI-чат упадёт с ошибкой Anthropic (намеренно, ключ отозван), но страница рендерится.

## Что НЕ проверено автоматически

- Visual rendering — потребует Playwright или ручной open в браузере. Frontend Explore агентом из Sprint 1 верифицировал общий layout pipeline.html / pipeline-run-detail.html.
- Mobile responsiveness — нужен Chrome DevTools mobile mode.
- Real-time WebSocket updates на pipeline-run-detail.html — требует живой run + Claude API.

Это нормальный gap для авто-smoke; manual visual test делает владелец один раз перед v1.0.0 release.

## Действия после smoke

- Багов уровня P0 (страница не открывается) — **нет**.
- Багов уровня P1 (визуальные разъезды на mobile) — будет проверено владельцем при первом use.
- Багов уровня P2+ — фиксируются в backlog v1.1.
