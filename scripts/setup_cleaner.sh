#!/usr/bin/env bash
# Install the stale-run cleaner agent. Runs at 06:00 and 18:00 IST, between
# the two syndicate.plist runs (11:59 and 23:59), and kills any pipeline
# process that's been alive longer than the threshold in clean_stale_runs.sh.
#
# Idempotent — re-run safely after editing the cleaner script or schedule.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="syndicate.cleaner"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
CLEANER="$REPO/scripts/clean_stale_runs.sh"
LOG_DIR="$REPO/logs"

mkdir -p "$LOG_DIR"
chmod +x "$CLEANER"

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
        <string>${CLEANER}</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>6</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/cleaner_agent.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/cleaner_agent.log</string>
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
echo "Cleaner agent loaded: $LABEL"

# ── Verify ──────────────────────────────────────────────────────────────────
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "Schedule: 06:00 and 18:00 daily (system local time)"
    echo "Logs    : ${LOG_DIR}/cleaner.log (script)  +  ${LOG_DIR}/cleaner_agent.log (stdout)"
    echo ""
    echo "Test on demand:  launchctl kickstart -p ${DOMAIN}/${LABEL}"
    echo "Uninstall:       launchctl bootout ${DOMAIN}/${LABEL} && rm ${PLIST}"
else
    echo "WARNING: launchctl print could not find ${LABEL} — agent may not be loaded."
    exit 1
fi
