from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _load_source_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fname in ("sources.json", "rss_sources.json"):
        path = _CONFIG_DIR / fname
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for src in data.get("sources", []):
            sid = src.get("id")
            dname = src.get("display_name")
            if sid and dname:
                mapping[sid] = dname
    return mapping


def _date_file_path(d: date) -> Path:
    """e.g. 2026/May/3-May-26.json"""
    return (
        Path(d.strftime("%Y"))
        / d.strftime("%B")
        / f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}.json"
    )


def _authenticated_url(base_url: str, pat: str | None) -> str:
    if pat and base_url.startswith("https://"):
        return base_url.replace("https://", f"https://{pat}@", 1)
    return base_url


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _row_to_dict(row: sqlite3.Row, source_map: dict[str, str]) -> dict:
    keys = row.keys() if hasattr(row, "keys") else []
    out = {
        "id": row["id"],
        "cluster_id": row["cluster_id"],
        "cluster_size": row["cluster_size"],
        "source": source_map.get(row["source_id"], row["source_id"]),
        "title": row["title"],
        "teaser": row["teaser"],
        "summary": row["summary"],
        "importance": row["importance"],
        "category": row["category"],
        "url": row["url"],
        "date": row["date"],
        "image_url": row["image_url"],
    }
    # New fields (Phase 1 of reactions-as-first-class plan): emit only when
    # the SELECT returned them, so this works against rows from any caller.
    if "source_channel" in keys:
        out["source_channel"] = row["source_channel"]
    if "relation" in keys:
        out["relation"] = row["relation"]
    if "parent_cluster_id" in keys:
        out["parent_cluster_id"] = row["parent_cluster_id"]
    if "author" in keys:
        out["author"] = row["author"]
    if "raw_meta" in keys and row["raw_meta"]:
        # raw_meta is JSON text in SQLite; expose as a dict in the feed.
        import json as _json
        try:
            out["raw_meta"] = _json.loads(row["raw_meta"])
        except (_json.JSONDecodeError, TypeError):
            pass
    return out


@dataclass
class GitExportResult:
    channel: str = "git_export"
    started_at: str = ""
    finished_at: str = ""
    ok: bool = True
    exported_today: int = 0
    exported_yesterday: int = 0
    committed: bool = False
    pushed: bool = False
    errors: list[str] = field(default_factory=list)


class GitExport:
    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
    ):
        self.db_path = Path(db_path)
        self._repo_url = os.environ.get("FEED_REPO_URL", "").strip() or None
        self._pat = os.environ.get("FEED_REPO_PAT", "").strip() or None
        self._source_map = _load_source_map()

        if self._repo_url:
            repo_name = self._repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            syndicate_dir = Path(__file__).resolve().parents[1]
            self.repo_path: Path | None = syndicate_dir.parent / repo_name
        else:
            self.repo_path = None

    def restore_snapshot(self, db_path: Path) -> bool:
        """Clone/pull feed repo, copy snapshot.db to db_path if found. Returns True if restored."""
        if not self.repo_path or not self._repo_url:
            return False
        try:
            self._ensure_repo()
        except Exception as exc:
            log.warning("Could not reach feed repo for snapshot restore: %s", exc)
            return False
        src = self.repo_path / "snapshot.db"
        if not src.exists():
            log.info("Feed repo has no snapshot.db — starting fresh DB")
            return False
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(db_path))
        log.info("Restored snapshot.db from feed repo (%d bytes)", src.stat().st_size)
        return True

    def run(self) -> GitExportResult:
        result = GitExportResult(started_at=now_iso())

        if not self.repo_path:
            result.errors.append("FEED_REPO_PATH not set — skipping git export")
            result.ok = False
            result.finished_at = now_iso()
            return result

        if not self._repo_url:
            result.errors.append("FEED_REPO_URL not set — skipping git export")
            result.ok = False
            result.finished_at = now_iso()
            return result

        try:
            self._ensure_repo()
        except Exception as exc:
            result.errors.append(f"repo setup failed: {exc}")
            result.ok = False
            result.finished_at = now_iso()
            return result

        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        with ItemStore(self.db_path) as store:
            today_count = self._write_date(store, today)
            yesterday_count = self._write_date(store, yesterday)

        result.exported_today = today_count
        result.exported_yesterday = yesterday_count
        total_new = today_count + yesterday_count

        if total_new == 0:
            log.info("git export: no new items — skipping commit")
            result.finished_at = now_iso()
            return result

        # Backup snapshot.db into the repo
        db_dest = self.repo_path / "snapshot.db"
        try:
            shutil.copy2(str(self.db_path), str(db_dest))
        except Exception as exc:
            log.warning("Could not copy snapshot.db: %s", exc)

        # Commit
        _git(["add", "-A"], self.repo_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        commit = _git(["commit", "-m", f"feed: {ts} (+{total_new} items)"], self.repo_path)

        if commit.returncode != 0:
            combined = commit.stdout + commit.stderr
            if "nothing to commit" in combined:
                log.info("git export: nothing new to commit")
                result.finished_at = now_iso()
                return result
            result.errors.append(f"git commit failed: {commit.stderr.strip()}")
            result.ok = False
            result.finished_at = now_iso()
            return result

        result.committed = True

        # Push
        push = _git(["push", "origin", "main"], self.repo_path)
        result.pushed = push.returncode == 0
        if not result.pushed:
            result.errors.append(f"git push failed: {push.stderr.strip()}")
            result.ok = False

        result.finished_at = now_iso()
        return result

    def _ensure_repo(self) -> None:
        auth_url = _authenticated_url(self._repo_url, self._pat)

        if not self.repo_path.exists():
            self.repo_path.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                ["git", "clone", auth_url, str(self.repo_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"git clone failed: {r.stderr.strip()}")
        else:
            _git(["pull", "--ff-only"], self.repo_path)

        # Keep authenticated remote URL current for push
        if self._pat:
            _git(["remote", "set-url", "origin", auth_url], self.repo_path)

    def _write_date(self, store: ItemStore, d: date) -> int:
        rel_path = _date_file_path(d)
        abs_path = self.repo_path / rel_path

        existing_ids: set[str] = set()
        existing_items: list[dict] = []
        if abs_path.exists():
            try:
                existing_items = json.loads(abs_path.read_text(encoding="utf-8"))
                existing_ids = {item["id"] for item in existing_items}
            except Exception as exc:
                log.warning("Could not parse %s: %s — will overwrite", abs_path, exc)

        rows = store.enriched_primary_items_for_date(d)
        new_items = [
            _row_to_dict(row, self._source_map)
            for row in rows
            if row["id"] not in existing_ids
        ]

        if not new_items:
            log.info("git export: %s — no new items", rel_path)
            return 0

        merged = existing_items + new_items
        merged.sort(key=lambda x: (-(x.get("importance") or 0), x.get("date") or ""))

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("git export: %s — +%d new (%d total)", rel_path, len(new_items), len(merged))
        return len(new_items)
