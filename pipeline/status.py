"""Read-only status snapshot of the syndicate pipeline.

Consumed by `/syndicate-status` and `/syndicate-heal` skills. Pure-read: no
writes to DB, no log file creation, no network state-change. Network ping to
Ollama is read-only and time-bounded.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.storage import DEFAULT_DB_PATH

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOGS_DIR = _REPO_ROOT / "logs"

# Env vars we report on. Grouped by which pipeline stage needs them so the
# /syndicate-heal skill can give targeted hints.
_ENV_KEYS: tuple[str, ...] = (
    "GMAIL_USER", "GMAIL_APP_PASSWORD",
    "AI_PROVIDER", "SUMMARIZE_MODEL", "EMBEDDING_MODEL", "EMBEDDING_PROVIDER",
    "OLLAMA_HOST",
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "MINIMAX_API_KEY",
    "VOYAGE_API_KEY", "COHERE_API_KEY",
    "FEED_REPO_URL", "FEED_REPO_PAT",
    "CHROME_EXECUTABLE", "CHROME_PROFILE_DIR", "TWITTER_HEADLESS",
    "TWITTER_BACKEND", "XQUIK_API_KEY", "XQUIK_BASE_URL",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "SYNDICATE_REPO",
)


@dataclass
class StatusSnapshot:
    db_path: str
    db_exists: bool
    db_size_bytes: int = 0
    items_total: int = 0
    items_last_24h: int = 0
    items_unsummarized: int = 0
    clusters_total: int = 0
    last_run_per_channel: dict[str, dict] = field(default_factory=dict)
    log_path_today: str | None = None
    log_tail: list[str] = field(default_factory=list)
    disk_free_gb: float = 0.0
    ollama_reachable: bool = False
    ollama_models_loaded: list[str] = field(default_factory=list)
    env_present: dict[str, bool] = field(default_factory=dict)
    twitter_backend: str = "playwright"
    git_branch: str | None = None
    git_dirty: bool = False
    errors: list[str] = field(default_factory=list)


def _query_db(db_path: Path, snap: StatusSnapshot) -> None:
    if not db_path.exists():
        return
    snap.db_size_bytes = db_path.stat().st_size
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM items")
        snap.items_total = cur.fetchone()[0]

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        cur.execute("SELECT COUNT(*) FROM items WHERE fetched_at >= ?", (cutoff,))
        snap.items_last_24h = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM items "
            "WHERE is_primary=1 AND summary IS NULL AND summarize_skip_reason IS NULL"
        )
        snap.items_unsummarized = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT cluster_id) FROM items WHERE cluster_id IS NOT NULL"
        )
        snap.clusters_total = cur.fetchone()[0]

        # Latest run per channel — runs is append-only, so MAX(run_id) is freshest.
        cur.execute(
            """
            SELECT r.channel, r.started_at, r.finished_at, r.ok,
                   r.fetched, r.saved, r.skipped, r.failed, r.errors
            FROM runs r
            JOIN (SELECT channel, MAX(run_id) AS rid FROM runs GROUP BY channel) m
              ON m.rid = r.run_id
            """
        )
        for row in cur.fetchall():
            errors_field = row["errors"]
            if errors_field:
                try:
                    errors_parsed: list[str] | str = json.loads(errors_field)
                except (json.JSONDecodeError, TypeError):
                    errors_parsed = errors_field
            else:
                errors_parsed = []
            snap.last_run_per_channel[row["channel"]] = {
                "started_at":  row["started_at"],
                "finished_at": row["finished_at"],
                "ok":          bool(row["ok"]) if row["ok"] is not None else None,
                "fetched":     row["fetched"],
                "saved":       row["saved"],
                "skipped":     row["skipped"],
                "failed":      row["failed"],
                "errors":      errors_parsed,
            }
        conn.close()
    except sqlite3.Error as e:
        snap.errors.append(f"sqlite: {e}")


def _read_log_tail(snap: StatusSnapshot, n: int = 20) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = _LOGS_DIR / f"{today}.txt"
    if not log_path.exists():
        return
    snap.log_path_today = str(log_path.relative_to(_REPO_ROOT))
    try:
        # Read whole file then take last N lines. Today's log is bounded
        # (~MB scale), so this is cheap and avoids seek/decode edge cases.
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        snap.log_tail = lines[-n:] if len(lines) > n else lines
    except OSError as e:
        snap.errors.append(f"log read: {e}")


def _check_ollama(snap: StatusSnapshot, timeout: float = 2.0) -> None:
    import os
    host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").strip()
    # OLLAMA_HOST in launchd is sometimes "0.0.0.0" which isn't a URL —
    # normalize to a usable URL for the probe.
    if not host.startswith("http"):
        host = f"http://{host}"
    url = f"{host.rstrip('/')}/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        snap.ollama_reachable = True
        snap.ollama_models_loaded = [m.get("name", "?") for m in data.get("models", [])]
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        snap.ollama_reachable = False
        log.debug("ollama probe failed: %s", e)


def _check_env(snap: StatusSnapshot) -> None:
    import os
    snap.env_present = {k: bool((os.environ.get(k) or "").strip()) for k in _ENV_KEYS}
    twitter_backend = (os.environ.get("TWITTER_BACKEND") or "").strip()
    snap.twitter_backend = (twitter_backend or "playwright").lower().replace("-", "_")


def _check_disk(snap: StatusSnapshot) -> None:
    try:
        usage = shutil.disk_usage(str(_REPO_ROOT))
        snap.disk_free_gb = round(usage.free / 1024**3, 2)
    except OSError as e:
        snap.errors.append(f"disk: {e}")


def _check_git(snap: StatusSnapshot) -> None:
    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=str(_REPO_ROOT),
                capture_output=True, text=True, timeout=5, check=False,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    snap.git_branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    porcelain = _git("status", "--porcelain")
    snap.git_dirty = bool(porcelain) if porcelain is not None else False


def snapshot(db_path: Path | str = DEFAULT_DB_PATH) -> StatusSnapshot:
    """Build a status snapshot. All checks are best-effort — partial data
    is preferred over raising."""
    db_path = Path(db_path)
    snap = StatusSnapshot(db_path=str(db_path), db_exists=db_path.exists())
    _query_db(db_path, snap)
    _read_log_tail(snap)
    _check_ollama(snap)
    _check_env(snap)
    _check_disk(snap)
    _check_git(snap)
    return snap


def snapshot_dict(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    return asdict(snapshot(db_path))
