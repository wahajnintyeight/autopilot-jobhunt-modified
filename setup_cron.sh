#!/bin/bash
# Sets up a cron job to run the job scan automatically.
# Usage: bash setup_cron.sh
#
# Customize these variables before running:
set -euo pipefail

PYTHON="${AUTOPILOT_PYTHON:-$(which python3)}"
CRON_TIME="${AUTOPILOT_CRON:-0 */6 * * *}"  # Default: every 6 hours

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG="$LOG_DIR/scan.log"

if [ ! -f "$PYTHON" ] && ! command -v "$PYTHON" &>/dev/null; then
    echo "Error: Python not found at '$PYTHON'"
    echo "Set AUTOPILOT_PYTHON=/path/to/python and re-run."
    exit 1
fi

mkdir -p "$LOG_DIR"

CRON_LINE="$CRON_TIME cd \"$PROJECT_DIR\" && AUTOPILOT_LOG_FILE=\"$LOG\" AUTOPILOT_CONSOLE_LOG=0 \"$PYTHON\" -m job_hunt.main scan >> \"$LOG\" 2>&1"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

crontab -l 2>/dev/null | grep -vF "job_hunt.main scan" > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"

echo "Cron job added: $CRON_TIME"
echo "Python: $PYTHON"
echo "Logs: $LOG"
echo ""
echo "To verify: crontab -l"
echo "To remove: crontab -e  (delete the line)"
echo ""
echo "To set a different time, use:"
echo "  AUTOPILOT_CRON='0 9 * * *' bash setup_cron.sh  # 9:00 AM daily"
