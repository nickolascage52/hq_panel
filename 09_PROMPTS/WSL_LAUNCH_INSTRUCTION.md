# Запуск AI Delivery Agent Team через WSL → tmux → Claude

Пошаговая инструкция для полноценного запуска команды агентов.

---

## Требования

- **WSL2** (Windows Subsystem for Linux)
- **tmux** — `sudo apt install tmux`
- **Claude CLI** с поддержкой Agent Teams (Claude Max или Pro с Opus)
- **settings.json** — `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"`

---

## ⚠️ Важно: два варианта запуска

**Вариант A — из PowerShell (рекомендуется):** запустит WSL автоматически
```powershell
cd "C:\Users\nikit\OneDrive\Рабочий стол\WorkPage\AI-запуск_обучение_инфопродукт\AI_Delivery_Team"
.\10_TMUX\scripts\start_team_from_powershell.ps1
```

**Вариант B — из WSL вручную:** открой WSL (`wsl`), затем выполни шаги ниже.

---

## Шаг 1: Открыть WSL и перейти в проект

```bash
# Сначала открой WSL: набери в PowerShell "wsl" или запусти Ubuntu из меню Пуск

# Вариант A: Прямой путь к проекту
cd "/mnt/c/Users/nikit/OneDrive/Рабочий стол/WorkPage/AI-запуск_обучение_инфопродукт/AI_Delivery_Team"

# Вариант B: Если проект скопирован в домашнюю папку WSL
# cd ~/AI_Delivery_Team

# Проверка: должен быть файл CLAUDE.md
ls CLAUDE.md
```

---

## Шаг 2: Запустить tmux-сессию с командой

```bash
bash 10_TMUX/scripts/start_team.sh
```

Откроется tmux с окнами:
- **0** chief-of-staff
- **1** content (strategist + telegram)
- **2** research (market + competitor)
- **3** website
- **4** ops & reports
- **5** **claude** ← сюда переходим

**Переключение между окнами:** `Ctrl+b` затем `0`–`5`

---

## Шаг 3: В окне «claude» запустить Claude

```bash
# Перейти в окно 5 (claude)
# Ctrl+b, затем 5

claude
# Или с флагом Agent Teams (если поддерживается):
# claude --agent-teams
```

---

## Шаг 4: Вставить промпт запуска

Скопируй промпт из **09_PROMPTS/LAUNCH_AGENT_TEAM.md** (раздел «Основной промпт») и вставь в Claude.

Или кратко:
```text
ПРЯМО СЕЙЧАС создай и запусти Команду Агентов. Запусти ровно 3 агента ОДНОВРЕМЕННО.
Контекст: CLAUDE.md, 00_MASTER/AGENCY_CONTEXT.md, 00_MASTER/TONE_OF_VOICE.md.
1. Market Researcher: 5 фактов об автоматизации МСБ 2025 → 03_RESEARCH/market/facts-msb-2025.txt
2. Telegram Lead: пост «ИИ-бот vs менеджер» → 02_CONTENT/telegram/drafts/draft-today.md
3. Content Strategist: промпт для Midjourney (бизнес-автоматизация) → 02_CONTENT/creative/image_prompt.txt
TeamCreate → TaskCreate. Запуск СТРОГО ПАРАЛЛЕЛЬНО!
```

---

## Шаг 5: Проверить результаты

После выполнения агентов проверь созданные файлы:

```bash
ls -la 03_RESEARCH/market/facts-msb-2025.txt
ls -la 02_CONTENT/telegram/drafts/draft-today.md
ls -la 02_CONTENT/creative/image_prompt.txt
```

Создать папку creative, если её нет:
```bash
mkdir -p 02_CONTENT/creative
```

---

## Управление tmux и отдача команд

### Навигация по окнам
| Действие | Комбинация |
|----------|-------------|
| Переключить окно | `Ctrl+b`, затем `0`–`5` |
| В окно Claude (главный агент) | `Ctrl+b` → `5` |
| Следующее / предыдущее окно | `Ctrl+b` `n` / `Ctrl+b` `p` |
| Список окон | `Ctrl+b` `w` |

### Как отдавать команды
- **Окно 5 (claude):** запусти `claude`, вставь промпт из LAUNCH_AGENT_TEAM.md — Claude запустит Agent Team
- **Окна 0–4:** в любом окне можно вызвать `claude --print "Ты [Агент]. Задача: ..."` для ручного запуска отдельного агента

### Сессия
| Действие | Команда |
|----------|---------|
| Отключиться (сессия работает) | `Ctrl+b`, затем `d` |
| Подключиться снова | `tmux attach -t ai_agency` |
| Закрыть сессию | `tmux kill-session -t ai_agency` |

---

## Troubleshooting

**Claude не находит файлы?**  
Убедись, что текущая директория — корень проекта (где лежит CLAUDE.md).

**Agent Teams не работают?**  
Проверь `settings.json` в проекте или глобально: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"`.

**TeamCreate/TaskCreate не найден?**  
Возможно, требуется Claude Max или другой план с доступом к Agent Teams. Уточни актуальную документацию Claude.
