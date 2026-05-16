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

# Free memory before the run — quits Cursor/VS Code, restarts Ollama. The 11.6 GB
# gemma4 model needs clean headroom on a 24 GB Mac, otherwise summarize crawls at
# ~30 min/item under memory pressure. Set SYNDICATE_SKIP_FREE_MEMORY=1 to opt out.
if [ -x "$REPO/scripts/free_memory.sh" ]; then
    bash "$REPO/scripts/free_memory.sh" || true
fi

# Run pipeline (headless Chrome for Twitter — no window needed in automated run)
TWITTER_HEADLESS=true "$HOME/.local/bin/uv" run syndicate >> "$LOG" 2>&1

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
