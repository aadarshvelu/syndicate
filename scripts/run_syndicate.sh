#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/syndicate.log"

mkdir -p "$LOG_DIR"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') START ===" >> "$LOG"

cd "$REPO"

# Strip launchd-injected OLLAMA_HOST=0.0.0.0 so .env's http://localhost:11434 wins.
unset OLLAMA_HOST

# Run pipeline
"$HOME/.local/bin/uv" run syndicate >> "$LOG" 2>&1

echo "=== $(date '+%Y-%m-%d %H:%M:%S') DONE ===" >> "$LOG"

# Schedule next wake (1 min before next run)
HOUR=$(date +%H)
if [ "$HOUR" -lt 18 ]; then
    NEXT="$(date '+%m/%d/%Y') 23:58:00"
else
    NEXT="$(date -v+1d '+%m/%d/%Y') 11:58:00"
fi

sudo pmset schedule wake "$NEXT"
echo "Next wake: $NEXT" >> "$LOG"

# Sleep
pmset sleepnow
