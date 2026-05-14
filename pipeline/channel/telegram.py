"""Telegram run-summary notifier.

Reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from env (or .env), takes
the orchestrator's `OrchestratorResult`, renders a compact mobile-friendly
summary, and posts to the bot's sendMessage endpoint.

The format is intentionally narrower than the terminal box drawing — wide
═ separators wrap badly on phones. We use a <pre> block so the per-stage
numbers stay column-aligned in Telegram's monospace font.

Failures are logged and swallowed — the notifier must never break the run.
"""

from __future__ import annotations

import html
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import is_dataclass
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TG_MAX = 4096   # Telegram message length cap
_NAME_W = 10     # column width for stage name — fits "Summarize "


class TelegramNotifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        *,
        timeout: int = 15,
    ) -> None:
        self.token = (token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        self.chat_id = (chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def notify(self, result: Any) -> bool:
        """Format `result` (OrchestratorResult or dict) and POST it.

        Returns True on a successful API ack, False if not configured or the
        call failed. Never raises — Telegram is best-effort.
        """
        if not self.configured:
            log.info(
                "Telegram not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) — skipping notify"
            )
            return False

        try:
            body = self._build_body(result)
        except Exception as exc:
            log.warning("Telegram format failed: %s", exc)
            return False

        return self._send(body)

    def _build_body(self, result: Any) -> str:
        # Lazy import to avoid cycles if orchestrator ever imports this module.
        from pipeline.orchestrator import OrchestratorResult

        if is_dataclass(result) and not isinstance(result, type):
            obj: OrchestratorResult = result  # type: ignore[assignment]
        elif isinstance(result, dict):
            obj = OrchestratorResult(**result)
        else:
            raise TypeError(
                f"TelegramNotifier.notify expected OrchestratorResult or dict, got {type(result).__name__}"
            )

        text = _format_compact(obj)
        escaped = html.escape(text, quote=False)
        wrapped = f"<pre>{escaped}</pre>"

        # Cap at Telegram's 4096-char limit — error lists can balloon.
        if len(wrapped) > _TG_MAX:
            overflow = len(wrapped) - _TG_MAX + 20
            escaped = escaped[: max(0, len(escaped) - overflow)] + "\n…[truncated]"
            wrapped = f"<pre>{escaped}</pre>"
        return wrapped

    def _send(self, text: str) -> bool:
        url = _API_URL.format(token=self.token)
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            log.warning("Telegram HTTP %s: %s", e.code, detail)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("Telegram send failed: %s", e)
            return False

        if not data.get("ok"):
            log.warning("Telegram API rejected message: %s", data)
            return False
        return True


def _duration(started_at: str, finished_at: str) -> str:
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        s = int((t1 - t0).total_seconds())
        return f"{s // 60}m {s % 60}s"
    except Exception:
        return "?"


def _tick(d: dict | None) -> str:
    return "✓" if (d and d.get("ok", True)) else "✗"


def _stage(name: str, d: dict | None, content: str) -> str:
    return f"{_tick(d)} {name:<{_NAME_W}}{content}"


def _format_compact(r: Any) -> str:
    """Mobile-friendly run summary. No box drawing, narrow columns."""
    dur = _duration(r.started_at, r.finished_at)
    ts = r.finished_at[:16].replace("T", " ") + " UTC"
    badge = "🟢" if r.ok else "🔴"

    lines = [f"{badge} SYNDICATE · {dur}", ts, ""]

    if r.gmail:
        g = r.gmail
        lines.append(_stage("Gmail", g, f"{g['fetched']} fetched · {g['saved']} saved"))
    if r.rss:
        x = r.rss
        lines.append(_stage("RSS", x, f"{x['fetched']} fetched · {x['saved']} saved"))
    if r.twitter:
        t = r.twitter
        lines.append(_stage("Twitter", t, f"{t['fetched']} fetched · {t['saved']} saved"))
    if r.relation:
        x = r.relation
        lines.append(_stage("Relation", x, f"{x['examined']} · {x['reactions']} reactions"))
    if r.dedup:
        d = r.dedup
        lines.append(_stage(
            "Dedup", d,
            f"{d['examined']} → {d['new_clusters']} clusters · −{d['items_demoted']} demoted",
        ))
    if r.summarize:
        s = r.summarize
        lines.append(_stage("Summarize", s, f"{s['examined']} → {s['summarized']} done"))
    if r.git:
        g = r.git
        bits = [f"+{g['exported_today']} today", f"+{g['exported_yesterday']} yesterday"]
        if g.get("pushed"):
            bits.append("pushed")
        elif g.get("committed"):
            bits.append("committed")
        lines.append(_stage("Git", g, " · ".join(bits)))

    if r.errors:
        lines.append("")
        lines.append("ERRORS:")
        for e in r.errors[:5]:
            lines.append(f"  • {str(e)[:200]}")
        if len(r.errors) > 5:
            lines.append(f"  … +{len(r.errors) - 5} more")

    return "\n".join(lines)
