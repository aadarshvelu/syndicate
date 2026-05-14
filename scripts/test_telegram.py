#!/usr/bin/env python3
"""Send a test run-summary to Telegram.

Usage:
    uv run python scripts/test_telegram.py
    uv run python scripts/test_telegram.py --discover   # auto-find chat_id

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from env (or .env). If chat_id
is missing or --discover is passed, calls getUpdates to find a chat the
bot has received a message from, prints it, and uses it for the send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

sys.path.insert(0, str(REPO))

from pipeline.channel.telegram import TelegramNotifier  # noqa: E402
from pipeline.orchestrator import OrchestratorResult  # noqa: E402


def _discover_chat_id(token: str) -> str | None:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        print(f"getUpdates failed: {data}")
        return None
    chats: list[tuple[int, str]] = []
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        name = chat.get("username") or chat.get("first_name") or chat.get("title") or "?"
        if cid and (cid, name) not in chats:
            chats.append((cid, name))
    if not chats:
        print(
            "No chats found. Send any message (e.g. /start) to your bot first,\n"
            "then re-run. Bot must have an existing inbound message before\n"
            "getUpdates returns anything."
        )
        return None
    print("Found chat(s):")
    for cid, name in chats:
        print(f"  chat_id={cid}  ({name})")
    chosen = str(chats[-1][0])
    print(f"\nUsing chat_id={chosen}. Add this to .env:")
    print(f"  TELEGRAM_CHAT_ID={chosen}")
    return chosen


def _sample_result() -> OrchestratorResult:
    """Build a result that mirrors the user-provided format example."""
    return OrchestratorResult(
        started_at="2026-05-12T07:59:07",
        finished_at="2026-05-12T09:37:50",
        ok=True,
        gmail={"ok": True, "fetched": 18, "saved": 2, "skipped": 16, "failed": 0},
        rss={"ok": True, "fetched": 53, "saved": 18, "skipped": 35, "failed": 0},
        twitter={"ok": True, "fetched": 82, "saved": 49, "skipped": 33, "failed": 0},
        relation={"ok": True, "examined": 293, "standalone": 291, "reactions": 2},
        dedup={
            "ok": True,
            "examined": 866,
            "new_clusters": 37,
            "items_demoted": 359,
            "matched_phase1": 9,
            "matched_phase2": 161,
            "method_counts": {
                "singleton": 341,
                "t4_semantic": 157,
                "t2_fuzzy": 4,
                "t1_exact": 5,
            },
        },
        summarize={"ok": True, "examined": 50, "summarized": 46, "skipped": 4},
        git={
            "ok": True,
            "exported_today": 12,
            "exported_yesterday": 34,
            "committed": True,
            "pushed": True,
        },
        errors=[],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a test Telegram run summary")
    ap.add_argument("--discover", action="store_true",
                    help="Always run getUpdates to find chat_id (ignores env)")
    args = ap.parse_args()

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in env or .env")
        return 1

    if args.discover or not chat_id:
        discovered = _discover_chat_id(token)
        if not discovered:
            return 1
        chat_id = discovered

    notifier = TelegramNotifier(token=token, chat_id=chat_id)
    print(f"\nSending test summary to chat_id={chat_id} ...")
    ok = notifier.notify(_sample_result())
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
