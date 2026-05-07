#!/usr/bin/env bash
# Run once on new machine to install launchd agent + first wake schedule.
# Requires sudo for pmset (wake scheduling).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="tech.elyts.syndicate"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
RUNNER="$REPO/scripts/run_syndicate.sh"
LOG_DIR="$REPO/logs"

mkdir -p "$LOG_DIR"
chmod +x "$RUNNER"

# ── Install deps ────────────────────────────────────────────────────────────
cd "$REPO"
"$HOME/.local/bin/uv" sync

# ── Write plist ─────────────────────────────────────────────────────────────
cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${RUNNER}</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>11</integer>
            <key>Minute</key>
            <integer>59</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>23</integer>
            <key>Minute</key>
            <integer>59</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/agent.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/agent_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>${HOME}</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

# ── Load agent ──────────────────────────────────────────────────────────────
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
echo "Agent loaded: $LABEL"

# ── Schedule first upcoming wake ────────────────────────────────────────────
NOW_H=$(date +%H)
NOW_M=$(date +%M)
TODAY=$(date '+%m/%d/%Y')
TOMORROW=$(date -v+1d '+%m/%d/%Y')

if [ "$NOW_H" -lt 11 ] || { [ "$NOW_H" -eq 11 ] && [ "$NOW_M" -lt 58 ]; }; then
    FIRST_WAKE="${TODAY} 11:58:00"
elif [ "$NOW_H" -lt 23 ] || { [ "$NOW_H" -eq 23 ] && [ "$NOW_M" -lt 58 ]; }; then
    FIRST_WAKE="${TODAY} 23:58:00"
else
    FIRST_WAKE="${TOMORROW} 11:58:00"
fi

sudo pmset schedule wake "$FIRST_WAKE"
echo "First wake scheduled: $FIRST_WAKE"

# ── Sudoers hint ────────────────────────────────────────────────────────────
echo ""
echo "NOTE: run_syndicate.sh calls 'sudo pmset' to reschedule wake each run."
echo "To avoid password prompts, add this line via: sudo visudo"
echo "  $(whoami) ALL=(ALL) NOPASSWD: /usr/bin/pmset"
echo ""
echo "Done. Logs → $LOG_DIR/"
