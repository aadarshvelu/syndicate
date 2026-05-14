#!/usr/bin/env bash
# Kill syndicate processes that have been running too long (likely stuck on
# IMAP / HTTP / Playwright). Runs from launchd at 6am and 6pm IST as a safety
# net between the two scheduled pipeline runs (11:59 and 23:59).
#
# If launchd sees a syndicate process still alive when the next schedule
# fires, the new instance is silently dropped — we hit a 32-hour hang on
# 2026-05-13 from exactly that. This cleaner unblocks future schedules.
#
# Threshold: 4 hours of elapsed time. A normal pipeline run takes 1-2 hours,
# so 4h is comfortable headroom while still catching real hangs.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/logs/cleaner.log"
THRESHOLD_SEC=14400      # 4 hours

mkdir -p "$(dirname "$LOG")"

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" >> "$LOG"; }

log "=== stale-run cleaner start ==="

# Match the three layers in the syndicate process tree:
#   bash scripts/run_syndicate.sh     ← launchd-spawned wrapper
#   uv run syndicate                  ← uv subprocess
#   .venv/bin/python ... syndicate    ← actual python
#
# Use pgrep -f to match against the FULL command line. Output is whitespace-
# separated PIDs (one per line). The pattern below covers all three.
#
# Portable to macOS /bin/bash (3.2): `mapfile` doesn't exist there, so read
# into an array via a while loop. Default empty to keep `set -u` happy.
PIDS=()
while IFS= read -r _pid; do
  [ -n "$_pid" ] && PIDS+=("$_pid")
done < <(pgrep -f 'run_syndicate\.sh|uv run syndicate|\.venv/bin/syndicate' 2>/dev/null || true)

if [ "${#PIDS[@]:-0}" -eq 0 ]; then
  log "no syndicate processes running — nothing to clean"
  log "=== done. killed=0 ==="
  exit 0
fi

KILLED=0
KEPT=0

for pid in "${PIDS[@]}"; do
  # Skip ourselves and our launchd-spawned parent shell.
  if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    continue
  fi

  # Get elapsed seconds (etimes gives integer seconds directly).
  ELAPSED=$(ps -p "$pid" -o etimes= 2>/dev/null | tr -d ' ')
  if [ -z "$ELAPSED" ] || ! [[ "$ELAPSED" =~ ^[0-9]+$ ]]; then
    log "skip pid=$pid (cannot read etime — likely already gone)"
    continue
  fi

  CMD=$(ps -p "$pid" -o command= 2>/dev/null | cut -c1-90)

  if [ "$ELAPSED" -gt "$THRESHOLD_SEC" ]; then
    log "STALE pid=$pid elapsed=${ELAPSED}s (>${THRESHOLD_SEC}s) — SIGTERM: $CMD"
    kill "$pid" 2>/dev/null && KILLED=$((KILLED + 1))
  else
    log "healthy pid=$pid elapsed=${ELAPSED}s — keep: $CMD"
    KEPT=$((KEPT + 1))
  fi
done

# Give SIGTERM 5 seconds to land, then escalate any survivors to SIGKILL.
if [ "$KILLED" -gt 0 ]; then
  sleep 5
  for pid in "${PIDS[@]}"; do
    if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then continue; fi
    if kill -0 "$pid" 2>/dev/null; then
      log "pid=$pid survived SIGTERM — escalating SIGKILL"
      kill -9 "$pid" 2>/dev/null
    fi
  done
fi

log "=== done. killed=$KILLED kept=$KEPT ==="
