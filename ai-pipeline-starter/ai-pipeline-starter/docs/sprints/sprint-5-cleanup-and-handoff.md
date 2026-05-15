# Sprint 5: Cleanup и AI Команда Deprecation

**Цель:** убрать или явно deprecate старую AI Команду, обновить документацию, провести smoke-test всего HQ.

**Длительность:** 2-3 дня по 2-3 часа.

**Зависимости:** Sprint 4 завершён, pipeline стабильно работает.

---

## Задачи

### T-5-001: Аудит использования старой AI Команды

**Type:** research
**Files:** `docs/ai-team-deprecation-plan.md`
**Acceptance:**
- Найти все места где используются:
  - `orchestrator.run_task()`
  - `agents.team.*`
  - `/api/task`, `/api/agents/*/chat`
  - `team.html`, `team-settings.html`
- Зафиксировать в `docs/ai-team-deprecation-plan.md`:
  - Где старая AI Команда вызывается из Telegram-бота
  - Какие команды бота от неё зависят (`/agent`, `/report` и т.д.)
  - Какие фронт-страницы используют
- Рекомендации: что можно удалить сразу, что заменить, что оставить «как есть»

**Estimate:** M (60 минут)
**Depends-on:** Sprint 4 done

---

### T-5-002: Решить судьбу Telegram команд

**Type:** decision
**Files:** `docs/ai-team-deprecation-plan.md` (обновить)
**Acceptance:**
- Решение принимается на основе T-5-001:
  - Вариант A: оставить старые команды бота работающими через старый orchestrator (минимальное вмешательство)
  - Вариант B: переписать `/agent`, `/report` под новый pipeline (если применимо)
  - Вариант C: убрать команды совсем (если они дублируют новый функционал)
- Зафиксировать решение в плане
- Закоммитить план

**Estimate:** S (30 минут)
**Depends-on:** T-5-001

---

### T-5-003: Применить решение по Telegram

**Type:** refactor
**Files:** `ai_agency/telegram_bot.py`
**Acceptance:**
- В соответствии с T-5-002, отредактировать `telegram_bot.py`
- Тестирование: запустить бота локально, проверить все команды
- Если что-то теперь не работает — fix до того как закоммитить

**Estimate:** L (60-90 минут)
**Depends-on:** T-5-002

---

### T-5-004: Пометить static/admin/ как deprecated

**Type:** cleanup
**Files:** `ai_agency/static/admin/`
**Acceptance:**
- Добавить файл `ai_agency/static/admin/DEPRECATED.md`:
  ```
  This admin panel is deprecated as of 2026-05-XX.
  Use /hq/ instead. This folder will be removed in v2.0.
  ```
- Не удаляем пока (риск что что-то использует)

**Estimate:** S (10 минут)
**Depends-on:** —

---

### T-5-005: Решить судьбу shell-агентов

**Type:** cleanup
**Files:** `AI_Delivery_Team/01_AGENTS/`, `AI_Delivery_Team/scripts/01..12_*.sh`, `launch_agents.sh`
**Acceptance:**
- Изучить эти файлы
- Решить: deprecate / delete / оставить как референс
- Если deprecate — добавить DEPRECATED.md в папки
- Если delete — git rm с понятным сообщением
- Если оставить — добавить README с пояснением что это и зачем

**Estimate:** M (45 минут)
**Depends-on:** —

---

### T-5-006: Обновить ai_agency/CLAUDE.md

**Type:** docs
**Files:** `ai_agency/CLAUDE.md`
**Acceptance:**
- Добавить раздел «AI Pipeline Module» с описанием:
  - Что это и зачем
  - Структура pipeline/ модуля
  - Как пользоваться (как создать pipeline-run)
  - Связь со старой AI Командой (deprecated)
- Обновить раздел «Архитектура» если нужно
- Обновить раздел «Грабли»
- Закоммитить

**Estimate:** M (60 минут)
**Depends-on:** —

---

### T-5-007: Обновить OWNER_GUIDE.md

**Type:** docs
**Files:** `ai_agency/OWNER_GUIDE.md`
**Acceptance:**
- Добавить раздел «Запуск pipeline-проектов» с пошаговой инструкцией
- Telegram-команды для управления pipeline (если есть)
- Что делать когда упёрся в rate limit
- Где смотреть логи pipeline

**Estimate:** M (45 минут)
**Depends-on:** —

---

### T-5-008: Smoke test всего HQ

**Type:** test
**Files:** —
**Acceptance:**
- Открыть каждую страницу HQ и проверить что она работает:
  - index.html — дашборд
  - crm.html
  - delivery.html (проверить что починен из Sprint 1)
  - project-detail.html
  - tasks.html, my-tasks.html
  - team.html (старая AI Команда — должна работать!)
  - team-settings.html
  - executors.html
  - channel.html
  - knowledge.html
  - notes.html
  - review.html
  - analytics.html
  - account.html
  - settings.html
  - guide.html
  - pipeline.html (новая!)
  - pipeline-run-detail.html (новая!)
- Любые баги — зафиксировать в issues GitHub
- Критичные — пофиксить сразу

**Estimate:** L (90-120 минут)
**Depends-on:** T-5-003, T-5-006

---

### T-5-009: Backlog для v1.1

**Type:** docs
**Files:** `docs/backlog-v1.1.md`
**Acceptance:**
- Записать что не вошло в v1, но стоит сделать:
  - Параллельные pipeline-runs
  - Полноценный чат с pipeline (как обсуждали в архитектуре)
  - Кастомные agent personas через UI
  - Поддержка типов проектов: telegram-bot, n8n, AI-ассистент
  - Cost tracking по runs
  - Voice input в Telegram через Whisper
  - GitHub OAuth
  - Multi-tenancy

**Estimate:** S (30 минут)
**Depends-on:** —

---

### T-5-010: Final release commit + tag

**Type:** release
**Files:** —
**Acceptance:**
- Все коммиты замерджены в main
- `git tag v1.0.0 -m "AI Pipeline Module v1.0 release"`
- `git push origin v1.0.0`
- Создать GitHub Release с описанием:
  - Что добавлено
  - Что deprecated
  - Migration guide (если нужно)

**Estimate:** S (30 минут)
**Depends-on:** все предыдущие задачи Sprint 5

---

## Definition of done for sprint 5

- [ ] Все задачи T-5-001..T-5-010 выполнены
- [ ] План deprecation AI Команды зафиксирован
- [ ] Telegram-бот работает (со старыми или новыми командами по решению)
- [ ] `static/admin/`, shell-агенты либо deprecated либо удалены
- [ ] Документация (CLAUDE.md, OWNER_GUIDE.md) обновлена
- [ ] Все страницы HQ работают (smoke test passed)
- [ ] Backlog v1.1 зафиксирован
- [ ] v1.0.0 tag создан

## Acceptance demo

После Sprint 5:

1. `git log --oneline` показывает чистую историю всех 5 спринтов
2. `git tag` показывает `v1.0.0`
3. GitHub Release v1.0.0 с описанием
4. Все страницы HQ открываются
5. Pipeline продолжает работать
6. Старая AI Команда либо работает (если оставили), либо deprecated явно
7. Документация обновлена и актуальна

## Что НЕ делаем в Sprint 5

- НЕ удаляем `agents/` модуль (риск сломать что-то незаметное)
- НЕ удаляем shell-агентов в `01_AGENTS/` (могут пригодиться)
- НЕ начинаем v1.1 — только бэклог

## Известные риски

- **При попытке поменять Telegram-бот можно его случайно сломать.** Тестировать каждое изменение перед commit.
- **Smoke test может выявить накопившиеся баги** от Sprint 1-4. Закладывать время на фиксы.
