# Sprint 1 — Findings Report

**Создан:** T-1-013
**Цель:** зафиксировать факты, обнаруженные по ходу Sprint 1, которые корректируют первоначальный аудит `docs/audit-2026-05-15.md`.

---

## Finding #1 (T-1-013): `/api/delivery/*` эндпоинты НЕ отсутствуют

### Statement в исходном аудите

`docs/audit-2026-05-15.md`, секция 4.6 (delivery.html) и 9.2 (Health check):

> ⚠ **`delivery.html` зовёт `/api/delivery/*`** — таких эндпоинтов в реестре api.py/hq_v3_api.py нет. Либо страница битая, либо эндпоинты в каком-то ещё файле (не нашёл). **Проверить руками.**

### Reality

**Все эндпоинты на месте в `ai_agency/api.py`** (lines 2395–3268). 19 routes в семействе `/api/delivery/*`:

| Метод | Путь | Файл:строка |
|---|---|---|
| GET | `/api/delivery/projects` | api.py:2395 |
| POST | `/api/delivery/projects` | api.py:2420 |
| GET | `/api/delivery/projects/{pid}` | api.py:2527 |
| PUT | `/api/delivery/projects/{pid}` | api.py:2549 |
| DELETE | `/api/delivery/projects/{pid}` | api.py:2602 |
| POST | `/api/delivery/projects/{pid}/apply_template` | api.py:2614 |
| GET | `/api/delivery/projects/{pid}/stages` | api.py:2636 |
| POST | `/api/delivery/projects/{pid}/stages` | api.py:2656 |
| PUT | `/api/delivery/stages/{sid}` | api.py:2688 |
| DELETE | `/api/delivery/stages/{sid}` | api.py:2709 |
| GET | `/api/delivery/tasks` | api.py:2721 |
| POST | `/api/delivery/tasks` | api.py:2784 |
| GET | `/api/delivery/tasks/{tid}` | api.py:2836 |
| PUT | `/api/delivery/tasks/{tid}` | api.py:2881 |
| DELETE | `/api/delivery/tasks/{tid}` | api.py:2932 |
| POST | `/api/delivery/tasks/{tid}/checklist` | api.py:2963 |
| POST | `/api/delivery/tasks/{tid}/comments` | api.py:2985 |
| GET | `/api/delivery/templates` | api.py:3218 |
| GET | `/api/delivery/overview` | api.py:3241 |

### Frontend сверка (delivery.html)

`ai_agency/static/hq/delivery.html` использует **только 4 endpoint'а**, и все четыре существуют:

| delivery.html line | Вызов | api.py соответствие |
|---|---|---|
| 512 | `apiAuth('/api/delivery/overview')` | api.py:3241 ✅ |
| 526 | `apiAuth('/api/delivery/projects')` | api.py:2395 ✅ |
| 536 | `apiAuth('/api/delivery/templates')` | api.py:3218 ✅ |
| 610 | `apiAuth('/api/delivery/projects', 'POST', payload)` | api.py:2420 ✅ |

### Verdict

**False alarm в первоначальном аудите.** Никакого фикса не требуется.

Что пошло не так в аудите: dispatched Explore agent пропустил секцию `/api/delivery/*` в `api.py`. Файл большой (128 KB, ~3300 строк), и agent не дочитал до строк 2395+. Также агент частично галлюцинировал список HTML-страниц (об этом я отметил тогда же).

**Действий не требуется. Sprint 2 НЕ блокирован «починкой delivery.html».**

### Поправка в audit-2026-05-15.md

В секции 9.2 (Health check) пункт «delivery.html зовёт /api/delivery/* — таких эндпоинтов в реестре нет» — **снимается**. Эндпоинты есть, страница работает.

В секции 8.4 (Риски при интеграции) пункт #7 «delivery.html может быть уже сломан в проде» — **тоже снимается**.

---

## Finding #2 (T-1-004): GitHub Push Protection поймал секрет до утечки

### Statement

При первом `git push` (T-1-004) GitHub автоматически отклонил коммит из-за обнаружения **Anthropic API Key** в `ai_agency/.env.example:2` коммита `5948fb5`.

### Действие

Хотфикс в рамках T-1-004: переписал `.env.example` placeholder'ами (что должно было сделаться в T-1-009), сделал `git commit --amend` и push прошёл. Новый SHA: `e56236a [T-1-003+009]`.

Старый SHA `5948fb5` существовал только локально — на GitHub НЕ ушёл. Утечки секретов в публичной истории нет.

### T-1-009 marker

Сделан `--allow-empty` коммит `f3a9408 [T-1-009]` для аудит-trail в `git log`.

---

## Finding #3 (T-1-012): Windows console encoding bug в main.py

### Statement

При smoke-тестах T-1-012 поймал `UnicodeEncodeError` в `main.py:192`:

```
logger.info("  [Старые URL] /admin и /panel → /hq/team.html")
                                              ^^^^^^^
UnicodeEncodeError: 'charmap' codec can't encode character '→'
```

Ошибка возникает только когда STDOUT перенаправлен в файл (через `Start-Process -RedirectStandardOutput`), и Windows консоль использует cp1251 (русская локаль). Если STDOUT идёт в живой терминал — не падает.

### Workaround в Sprint 1

При запуске python — установить `PYTHONIOENCODING=utf-8` в окружении.

### Permanent fix (Sprint 5 cleanup)

Один из двух вариантов:
- (a) Заменить `→` на `->` в `main.py:192` (минимальный diff)
- (b) Установить `PYTHONIOENCODING=utf-8` в `install.sh` и в systemd-юните на проде (более correct, но трогает install/deploy)

Не блокер для Sprint 1. На проде Linux нет cp1251, не воспроизводится.

---

## Finding #4 (T-1-012): Force-logout-on-deploy by design

### Statement

Миграция T-1-012 (in-memory `_sessions: dict` → таблица `hq_sessions`) при первом деплое на любую инстанцию **разлогинит всех текущих пользователей**, потому что in-memory dict пустеет, а БД-таблица только что создана и пуста.

### Это намеренно

По решению владельца (см. AskUserQuestion от 2026-05-15): «Force logout всех — простая логика, чистый старт». Альтернативы (миграция активных сессий, auto-create записей по неизвестному токену) отвергнуты как сложные/рискованные.

### Симптом для пользователей

После рестарта сервиса (включая T-1-016 на проде) — все откроют HQ → редирект на login.html → логин с НОВЫМ ADMIN_PASSWORD (`WMhA3aejzKjk03OHez8iSjtV`).

### Не баг, не риск

Это контракт миграции, описанный в `pure-gliding-wand.md` → блок C.

---

## Сводная таблица «что в плане сейчас неточно»

| Документ | Что неточно | Замена |
|---|---|---|
| `docs/audit-2026-05-15.md` § 4.6, 8.4#7, 9.2 | «delivery.html зовёт несуществующие эндпоинты» | Эндпоинты ЕСТЬ (api.py:2395-3268). False alarm. |
| `pure-gliding-wand.md` блок D, T-1-013 «починка delivery.html» | Подразумевалось что эндпоинтов может не быть → создавать stub'ы | Эндпоинты есть, фикс **не нужен**. T-1-013 = только этот отчёт. |

---

_Документ обновляется по ходу спринта. Финальная версия — после T-1-016._
