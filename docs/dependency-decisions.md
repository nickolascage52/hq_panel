# Dependency Decisions

Решения по зависимостям проекта. Обновляется по ходу спринтов.

---

## T-2-001 (2026-05-15): claude-agent-sdk совместим с anthropic<1

### Тест

В изолированном venv (`%TEMP%\test_sdk_venv`, Python 3.13):

```bash
python -m venv %TEMP%\test_sdk_venv
%TEMP%\test_sdk_venv\Scripts\python.exe -m pip install claude-agent-sdk
%TEMP%\test_sdk_venv\Scripts\python.exe -m pip install "anthropic>=0.40,<1"
```

### Результат: чистая установка, без конфликтов

| Пакет | Установленная версия | Пинн в нашем `requirements.txt` | Совместимо? |
|---|---|---|---|
| `claude-agent-sdk` | 0.2.82 | (новый) | — |
| `anthropic` | 0.102.0 | `>=0.40.0,<1` | ✅ в диапазоне |
| `httpx` | 0.28.1 | `>=0.27.0,<1` | ✅ в диапазоне |
| `httpx-sse` | 0.4.3 | (transitive, новый) | ✅ |
| `pydantic` | 2.13.4 | `>=2.10.0,<3` | ✅ в диапазоне |
| `pydantic-core` | 2.46.4 | (transitive) | ✅ |
| `pydantic-settings` | 2.14.1 | (новый, transitive) | ✅ |
| `jiter` | 0.14.0 | (новый, transitive) | ✅ |
| `docstring-parser` | 0.18.0 | (новый, transitive) | ✅ |
| `distro` | 1.9.0 | (новый, transitive) | ✅ |

### Smoke import

```python
import anthropic                 # version 0.102.0 ✅
import claude_agent_sdk          # импортируется ✅
# Доступные API: AgentDefinition, AssistantMessage, ClaudeAgentOptions,
#   ClaudeSDKClient, ClaudeSDKError, ContentBlock, ...
```

### О старом комментарии в requirements.txt

Текущий `requirements.txt` содержит комментарий:

```
# 0.25.x ломается с httpx 0.28+ (TypeError: unexpected keyword argument 'proxies')
anthropic>=0.40.0,<1
httpx>=0.27.0,<1
```

Этот комментарий относится к **anthropic 0.25.x**, а не к нашему диапазону `>=0.40`. У нас уже свежий anthropic, проблема не воспроизводится. Комментарий можно оставить как исторический — он информативен для тех, кто захочет даунгрейдить anthropic.

### Решение

**Использовать единый основной venv.** `claude-agent-sdk` устанавливается рядом с существующими зависимостями без конфликтов.

В `requirements.txt` добавляются:
```
claude-agent-sdk>=0.2.0,<1     # Sprint 2: pipeline module
GitPython>=3.1.0               # Sprint 2: pipeline workspace git ops
```

`claude-agent-sdk>=0.2.0,<1` — широкий, но `<1` минор не должен ломать API (по semver). Если SDK выпустит 1.0 — пересмотрим в Sprint 5.

### Риски на будущее

1. **anthropic-sdk дрифтит между минор-версиями.** При следующем `pip install --upgrade` могут обновиться зависимости. Митигация: пинн `<1` уже есть.
2. **claude-agent-sdk молодой** (v0.2.x). Возможны breaking changes между минор-версиями. Митигация: фиксируем `>=0.2.0` минимум, регулярно проверяем changelog при upgrade.

### Поправка (T-2-002 во время фактической установки)

Изначальный план «установить в основной venv без изменений» НЕ сработал из-за конфликта:
- `claude-agent-sdk` → `mcp>=1.23.0` → `starlette>=0.46` → требует `fastapi>=0.115`
- Наш пин `fastapi==0.110.0` (требует `starlette<0.37`) — БЛОКИРОВАЛ установку
- Наш пин `uvicorn==0.27.0` тоже не пускал

**Решение применено в T-2-002:**

| Пакет | Старый pin | Новый pin | Установлено |
|---|---|---|---|
| `fastapi` | `==0.110.0` | `>=0.115,<1` | 0.136.1 |
| `uvicorn` | `==0.27.0` | `>=0.27.0,<1` | 0.47.0 |
| `starlette` | (transitive) | (transitive) | 1.0.0 |
| `claude-agent-sdk` | (новый) | `>=0.2.0,<1` | 0.2.82 |
| `GitPython` | (новый) | `>=3.1.0` | 3.1.50 |

**Smoke-test после установки:** main.py стартует чисто на новом стеке (WEB_ONLY=true, 10 сек, STDERR пустой).

### Риски новых пинов

1. **fastapi 0.110 → 0.136** — большой скачок. FastAPI декларирует обратную совместимость для core API, но breaking changes возможны в edge cases (depricated параметры Body/Form). При первой ошибке смотрим CHANGELOG между 0.110 и 0.136. Smoke main.py прошёл — основные пути работают.
2. **uvicorn 0.27 → 0.47** — новые reload/lifespan параметры могут менять поведение. На проде проверим в T-1-016.
3. **starlette 1.0 (мажор)** — много изменений API. Если в `api.py` или `hq_v3_api.py` используется starlette напрямую (не через FastAPI) — могут быть проблемы. Grep не нашёл прямых импортов starlette → безопасно.

---
