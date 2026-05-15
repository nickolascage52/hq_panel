#!/bin/bash
# Запуск AI Growth команды в tmux
# Запускай из WSL: wsl, затем cd в проект, затем bash 10_TMUX/scripts/start_team.sh

SESSION="ai_agency"
# Рабочая директория: корень проекта (где лежит CLAUDE.md)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Проверка: tmux должен быть установлен
if ! command -v tmux &>/dev/null; then
  echo "Ошибка: tmux не найден. Установи: sudo apt install tmux (в WSL)"
  exit 1
fi

# Убиваем старую сессию если есть
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Создаём новую сессию (пути в кавычках из-за пробелов)
tmux new-session -d -s "$SESSION" -n "chief" -c "$WORKDIR" || {
  echo "Ошибка: не удалось создать tmux-сессию. Проверь путь к проекту."
  exit 1
}

# Окно 0: Chief of Staff
tmux rename-window -t "$SESSION:0" "chief-of-staff"
tmux send-keys -t "$SESSION:0" "echo '=== CHIEF OF STAFF ===' && cat 01_AGENTS/chief_of_staff/SYSTEM_PROMPT.md | head -5" Enter

# Окно 1: Content
tmux new-window -t "$SESSION" -n "content" -c "$WORKDIR"
tmux split-window -h -t "$SESSION:1"
tmux send-keys -t "$SESSION:1.0" "echo '=== CONTENT STRATEGIST ===' && cat CLAUDE.md | head -10" Enter
tmux send-keys -t "$SESSION:1.1" "echo '=== TELEGRAM LEAD ===' && cat 01_AGENTS/telegram_lead/SYSTEM_PROMPT.md | head -5" Enter

# Окно 2: Research
tmux new-window -t "$SESSION" -n "research" -c "$WORKDIR"
tmux split-window -h -t "$SESSION:2"
tmux send-keys -t "$SESSION:2.0" "echo '=== MARKET RESEARCHER ===' " Enter
tmux send-keys -t "$SESSION:2.1" "echo '=== COMPETITOR ANALYST ===' " Enter

# Окно 3: Website
tmux new-window -t "$SESSION" -n "website" -c "$WORKDIR"
tmux split-window -h -t "$SESSION:3"
tmux send-keys -t "$SESSION:3.0" "echo '=== WEBSITE STRATEGIST ===' " Enter
tmux send-keys -t "$SESSION:3.1" "echo '=== CRO/UX + COPYWRITER ===' " Enter

# Окно 4: OPS & Reports
tmux new-window -t "$SESSION" -n "ops" -c "$WORKDIR"
tmux send-keys -t "$SESSION:4" "echo '=== OPS & REPORTS ===' && ls 07_OPS/" Enter

# Окно 5: Claude Code (главный агент)
tmux new-window -t "$SESSION" -n "claude" -c "$WORKDIR"
tmux send-keys -t "$SESSION:5" "echo 'Запустите: claude' && echo 'Или для Agent Teams: claude --agent-teams'" Enter

# Переходим на главное окно
tmux select-window -t "$SESSION:0"

echo "=== AI Agency Team запущена ==="
echo "Подключиться: tmux attach -t $SESSION"
echo ""
echo "Окна:"
echo "  0: chief-of-staff"
echo "  1: content (strategist + telegram)"
echo "  2: research (market + competitor)"
echo "  3: website (strategist + cro/copywriter)"
echo "  4: ops & reports"
echo "  5: claude (main agent)"

tmux attach -t "$SESSION"
