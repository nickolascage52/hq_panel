#!/bin/bash
# T-1-015 (Sprint 1): rotate agency.db backups, keep latest N.
#
# Usage:
#   /var/www/ai_agency/ai_agency/scripts/rotate_backups.sh
#
# Cron (T-1-016 will install this):
#   0 4 * * * /var/www/ai_agency/ai_agency/scripts/rotate_backups.sh >> /var/log/ai-agency-rotate.log 2>&1
#
# Behavior:
#   - Looks at $BACKUP_DIR (defaults to ../backups relative to this script).
#   - Sorts files matching agency_*.db by modification time (newest first).
#   - Deletes everything past position $KEEP.
#   - Idempotent: if fewer than $KEEP backups exist, does nothing.

set -euo pipefail

KEEP="${KEEP:-30}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/../backups}"

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "[$(date -Iseconds)] backup dir not found: $BACKUP_DIR — nothing to do"
    exit 0
fi

cd "$BACKUP_DIR"

# Count current backups matching the pattern.
total=$(find . -maxdepth 1 -type f -name 'agency_*.db' 2>/dev/null | wc -l | tr -d ' ')

if [[ "$total" -le "$KEEP" ]]; then
    echo "[$(date -Iseconds)] $total backups present, threshold $KEEP not exceeded — keep all"
    exit 0
fi

# Files to delete = total - KEEP (oldest first).
to_delete=$((total - KEEP))

# ls -t sorts newest first; tail -n +$((KEEP+1)) yields rows from position KEEP+1 onward (oldest).
# Use -- to separate flags from possible filenames starting with '-'.
deleted_count=0
ls -t -- agency_*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r file; do
    rm -f -- "$file"
    deleted_count=$((deleted_count + 1))
    echo "[$(date -Iseconds)] removed $file"
done

remaining=$(find . -maxdepth 1 -type f -name 'agency_*.db' 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date -Iseconds)] rotation complete: removed=$to_delete, remaining=$remaining (target=$KEEP)"
