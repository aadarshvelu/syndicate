#!/usr/bin/env bash
# Memory-clearing pre-step for the syndicate pipeline.
#
# Called automatically by run_syndicate.sh before `uv run syndicate` kicks
# off. The goal: get Ollama a clean 24 GB of headroom on this Mac so the
# 11.6 GB gemma4 model doesn't fight Cursor/VS Code for resident pages.
#
# What it does, in order:
#   1. Politely quit Cursor + VS Code via osascript (lets them save state)
#   2. Wait 10s for graceful shutdown
#   3. Hard-kill any stragglers (Cursor Helper, Vite, etc.)
#   4. Restart Ollama (releases the resident model + any leaked state)
#   5. Wait until Ollama HTTP endpoint is ready again (max 180s)
#
# Skip with:   SYNDICATE_SKIP_FREE_MEMORY=1
# Dry-run:     bash scripts/free_memory.sh --dry-run
#
# Always exits 0 — failures here are non-fatal for the pipeline. Logs to
# logs/free_memory.log so you can audit later.

set -u

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/logs/free_memory.log"
mkdir -p "$(dirname "$LOG")"

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" | tee -a "$LOG" >&2; }

if [ "${SYNDICATE_SKIP_FREE_MEMORY:-0}" = "1" ]; then
    log "=== skipped (SYNDICATE_SKIP_FREE_MEMORY=1) ==="
    exit 0
fi

[ $DRY_RUN -eq 1 ] && log "=== free_memory DRY-RUN start (no kills, no restart) ===" \
                   || log "=== free_memory start ==="

# Memory free in MB. macOS page size is 16 KB on Apple Silicon, 4 KB on Intel.
# Read it via sysctl rather than assuming.
_mem_free_mb() {
    local page_size free spec
    page_size=$(sysctl -n hw.pagesize 2>/dev/null || echo 16384)
    free=$(vm_stat | awk '/Pages free/        {gsub("\\.","",$3); print $3}')
    spec=$(vm_stat | awk '/Pages speculative/ {gsub("\\.","",$3); print $3}')
    free=${free:-0}; spec=${spec:-0}
    echo $(( (free + spec) * page_size / 1024 / 1024 ))
}

log "memory free before: $(_mem_free_mb) MB"

# ── 1. Politely quit memory-hog GUI apps ─────────────────────────────────────
# These are the ones we've observed eating multiple GB on this Mac. Add more
# here if needed (Slack, Spotify, browser-with-100-tabs, etc).
APPS_TO_QUIT=("Cursor" "Visual Studio Code")

for app in "${APPS_TO_QUIT[@]}"; do
    if pgrep -f "$app" >/dev/null 2>&1; then
        if [ $DRY_RUN -eq 1 ]; then
            log "[dry-run] WOULD quit: $app"
        else
            log "quitting $app..."
            osascript -e "tell application \"$app\" to quit" 2>/dev/null || true
        fi
    fi
done

# ── 2. Wait for graceful shutdown ────────────────────────────────────────────
[ $DRY_RUN -eq 0 ] && sleep 10

# ── 3. Hard-kill any stragglers ──────────────────────────────────────────────
# After `osascript … quit Cursor`, Cursor's children often DON'T die — they
# reparent to launchd (PID 1) and keep running. Common offenders on this Mac:
#
#   - Claude Code extension processes
#       /Users/aveey/.cursor-server/extensions/anthropic.claude-code-*/
#         resources/native-binary/claude --output-format stream-json ...
#   - MCP servers spawned by Cursor's mcp.json
#       node /Users/aveey/dsrcs/poly-mcp/dist/index.js
#       npm exec @railway/mcp-server
#       node /Users/aveey/.npm/_npx/.../railway-mcp-server
#   - Vite dev servers launched from Cursor terminals
#
# Patterns are still narrow enough to avoid killing unrelated dev work in
# other terminals (e.g. a standalone `node server.js` won't match "node.*vite").
STRAGGLER_PATTERNS=(
    "Cursor Helper"
    "Code Helper"
    "node.*vite"
    ".cursor-server/extensions"     # all remote-server extension hosts (Claude Code etc.)
    "mcp"                           # railway-mcp-server, poly-mcp, any MCP server
)

for pat in "${STRAGGLER_PATTERNS[@]}"; do
    pids=$(pgrep -f "$pat" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        # Don't kill ourselves or our parent shell (paranoia — pgrep -f could
        # match this very script's command-line in weird cases).
        pids=$(echo "$pids" | grep -v "^$$\$\|^$PPID\$" || true)
        if [ -n "$pids" ]; then
            if [ $DRY_RUN -eq 1 ]; then
                log "[dry-run] WOULD hard-kill matching '$pat': $(echo $pids)"
            else
                log "hard-killing stragglers matching '$pat': $(echo $pids)"
                echo "$pids" | xargs kill -9 2>/dev/null || true
            fi
        fi
    fi
done

# ── 4. Restart Ollama (headless `ollama serve`, no UI) ──────────────────────
# We don't want the Mac app's UI window in cron context — just the HTTP
# daemon. Kill the app + any running serve/runner, then start a fresh
# `ollama serve` in the background, fully detached from this script.
OLLAMA_BIN=$(command -v ollama 2>/dev/null || echo "/Applications/Ollama.app/Contents/Resources/ollama")
OLLAMA_LOG="$REPO/logs/ollama_serve.log"

if [ $DRY_RUN -eq 1 ]; then
    log "[dry-run] WOULD quit Ollama app + restart headless: $OLLAMA_BIN serve > $OLLAMA_LOG"
else
    log "restarting Ollama (headless serve only)..."
    osascript -e 'tell application "Ollama" to quit' 2>/dev/null || true
    pkill -f "Ollama.app/Contents/MacOS/Ollama" 2>/dev/null || true
    pkill -f "ollama serve"   2>/dev/null || true
    pkill -f "ollama runner"  2>/dev/null || true
    sleep 2
    # Subshell + nohup + disown detaches the serve process from this script's
    # process group so it survives after free_memory.sh exits. </dev/null on
    # stdin prevents any tty-related blocking.
    ( nohup "$OLLAMA_BIN" serve > "$OLLAMA_LOG" 2>&1 < /dev/null & disown ) || true
fi

# ── 5. Wait for Ollama HTTP to come back ready ──────────────────────────────
if [ $DRY_RUN -eq 0 ]; then
    for i in $(seq 1 90); do
        if curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
            log "ollama ready after $((i * 2)) seconds"
            break
        fi
        sleep 2
        if [ "$i" = 90 ]; then
            log "WARN: ollama not reachable after 180s — pipeline will fail at summarize"
        fi
    done
fi

log "memory free after: $(_mem_free_mb) MB"
[ $DRY_RUN -eq 1 ] && log "=== free_memory DRY-RUN done ===" \
                   || log "=== free_memory done ==="

exit 0
