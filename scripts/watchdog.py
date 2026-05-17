#!/usr/bin/env python3
"""Standalone freshness watchdog for the syndicate pipeline.

Independent of the orchestrator — runs on its own launchd schedule. The
point: when the pipeline silently stops working (process killed, Ollama
dies, launchd disabled, etc.) the orchestrator's own Telegram notify
never fires, and the failure is invisible until someone opens the PWA
and notices stale news.

This watchdog reads the `runs` table directly via sqlite3, computes the
age of the newest per-channel run, and pings Telegram if anything is
stale beyond the threshold. No pipeline imports — works even if the
pipeline code is broken.

Run on demand:
    uv run python scripts/watchdog.py

Schedule via launchd:
    cp scripts/syndicate.watchdog.plist ~/Library/LaunchAgents/
    launchctl load -w ~/Library/LaunchAgents/syndicate.watchdog.plist

Exit codes:
    0  all channels fresh
    1  at least one channel stale (alert fired if Telegram configured)
    2  cannot read DB (alert fired if Telegram configured)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "db" / "snapshot.db"
_ENV = _REPO / ".env"
if _ENV.exists():
    load_dotenv(_ENV)

# Channels we expect to see a fresh run for. Skip a channel by setting
# WATCHDOG_SKIP_<CHANNEL>=1 (e.g. WATCHDOG_SKIP_TWITTER=1 if you're not
# using Twitter on this machine).
_CHANNELS = ("gmail", "rss", "twitter")

# Default staleness threshold. Each scheduled run interval is 12h, so 24h
# means "at least two scheduled cycles have failed silently".
_STALE_HOURS_DEFAULT = 24.0

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("watchdog")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_ago(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return (_now_utc() - ts).total_seconds() / 3600.0


def _latest_runs() -> dict[str, dict]:
    """Return {channel: {finished_at, ok, errors}} for the most recent run per channel."""
    if not _DB.exists():
        raise FileNotFoundError(f"DB not found at {_DB}")
    con = sqlite3.connect(str(_DB))
    con.row_factory = sqlite3.Row
    try:
        # runs is append-only; MAX(run_id) is the freshest row per channel.
        rows = con.execute(
            """
            SELECT r.channel, r.finished_at, r.ok, r.errors
            FROM runs r
            JOIN (SELECT channel, MAX(run_id) AS rid FROM runs GROUP BY channel) m
              ON m.rid = r.run_id
            """
        ).fetchall()
    finally:
        con.close()
    return {r["channel"]: dict(r) for r in rows}


def _telegram(token: str, chat_id: str, text: str) -> bool:
    """Post one HTML message to Telegram. Never raises — returns True on 200."""
    if not (token and chat_id):
        log.info("Telegram not configured — skipping alert")
        return False
    url = _TG_API.format(token=token)
    payload = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                log.warning("Telegram returned %d: %s", resp.status, resp.read()[:200])
                return False
            return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("Telegram POST failed: %s", exc)
        return False


def _build_alert(report: list[dict], stale_threshold: float) -> str:
    """Render an HTML Telegram message from the per-channel report."""
    lines = [
        "<b>🚨 syndicate watchdog</b>",
        f"<i>One or more channels stale beyond {stale_threshold:.0f}h</i>",
        "",
        "<pre>",
    ]
    for r in report:
        ch = r["channel"]
        age = r["age_hours"]
        if age is None:
            lines.append(f"  {ch:<8} (no successful run ever recorded)")
        else:
            tick = "✗" if age > stale_threshold else "✓"
            ok_marker = "" if r.get("ok") else " (last run errored)"
            lines.append(f"  {tick} {ch:<8} {age:5.1f}h ago{ok_marker}")
    lines.append("</pre>")
    return "\n".join(lines)


def main() -> int:
    stale_threshold = float(os.environ.get("WATCHDOG_STALE_HOURS") or _STALE_HOURS_DEFAULT)

    try:
        runs = _latest_runs()
    except Exception as exc:
        log.error("Cannot read runs table: %s", exc)
        _telegram(
            os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            os.environ.get("TELEGRAM_CHAT_ID", ""),
            f"<b>🚨 syndicate watchdog</b>\n<i>Cannot read DB</i>\n<pre>{exc}</pre>",
        )
        return 2

    report: list[dict] = []
    for ch in _CHANNELS:
        if os.environ.get(f"WATCHDOG_SKIP_{ch.upper()}") == "1":
            continue
        latest = runs.get(ch)
        finished = _parse_iso(latest.get("finished_at")) if latest else None
        age = _hours_ago(finished)
        report.append({
            "channel":   ch,
            "age_hours": age,
            "ok":        bool(latest.get("ok")) if latest else False,
        })

    stale = [r for r in report if (r["age_hours"] is None or r["age_hours"] > stale_threshold)]

    if not stale:
        log.info(
            "OK — all channels fresh (worst: %.1fh)",
            max(r["age_hours"] for r in report if r["age_hours"] is not None),
        )
        return 0

    log.warning("STALE — %d channel(s) over threshold (%s)",
                len(stale), [r["channel"] for r in stale])
    sent = _telegram(
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_ID", ""),
        _build_alert(report, stale_threshold),
    )
    log.info("Telegram alert %s", "sent" if sent else "NOT sent")
    return 1


if __name__ == "__main__":
    sys.exit(main())
