#!/bin/bash
# Запуск ежедневного цикла работы команды

DATE=$(date +%Y-%m-%d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="$WORKDIR/07_OPS/daily_logs/$DATE.md"

echo "=== DAILY CYCLE: $DATE ==="

# Создаём лог файл если не существует
if [ ! -f "$LOG_FILE" ]; then
    cp "$WORKDIR/07_OPS/daily_logs/TEMPLATE_daily_log.md" "$LOG_FILE"
    sed -i "s/\[ДАТА\]/$DATE/g" "$LOG_FILE"
    echo "✅ Создан daily log: $LOG_FILE"
fi

# Показываем backlog
echo ""
echo "=== ТЕКУЩИЙ BACKLOG ==="
grep "- \[ \]" "$WORKDIR/07_OPS/backlog/backlog.md" | head -10

echo ""
echo "=== ЗАПУСК КОМАНДЫ ==="
echo "1. Откройте tmux: bash 10_TMUX/scripts/start_team.sh"
echo "2. В окне 'claude' запустите: claude"
echo "3. Вставьте промпт Chief of Staff для планирования дня"
echo ""
echo "Daily log создан: $LOG_FILE"
