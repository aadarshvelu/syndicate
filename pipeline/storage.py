"""SQLite-backed item store for the news digest pipeline.

Schema:
  - items: one row per ingested article. Primary key is a random UUIDv4;
    dedup_key (sha1 over URL or message-id+title) carries a UNIQUE index so
    re-running the pipeline does not double-insert.
  - runs: append-only log of pipeline runs (channel, counts, errors).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("db") / "snapshot.db"

# Tables only — runs first. Indexes that reference newer columns must wait
# until _ensure_columns has had a chance to ALTER pre-migration tables.
_TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id              TEXT PRIMARY KEY,
  dedup_key       TEXT UNIQUE NOT NULL,
  source_id       TEXT NOT NULL,
  source_channel  TEXT NOT NULL,
  title           TEXT,
  desp            TEXT,
  date            TEXT,
  content         TEXT,
  is_html         INTEGER NOT NULL DEFAULT 0,
  url             TEXT,
  author          TEXT,
  fetched_at      TEXT NOT NULL,
  raw_meta        TEXT,
  summary         TEXT,
  importance      INTEGER,
  category        TEXT,
  cluster_id      TEXT,
  is_primary      INTEGER NOT NULL DEFAULT 1,
  cluster_method  TEXT,
  embedding       BLOB
);

CREATE TABLE IF NOT EXISTS runs (
  run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  channel         TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  ok              INTEGER,
  fetched         INTEGER,
  saved           INTEGER,
  skipped         INTEGER,
  failed          INTEGER,
  errors          TEXT
);
"""

_INDEXES_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_channel, source_id);
CREATE INDEX IF NOT EXISTS idx_items_date ON items(date);
CREATE INDEX IF NOT EXISTS idx_items_fetched_at ON items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_items_primary ON items(is_primary);
CREATE INDEX IF NOT EXISTS idx_runs_channel ON runs(channel, started_at);
"""

_DEDUP_COLUMNS = (
    ("cluster_id", "TEXT"),
    ("is_primary", "INTEGER NOT NULL DEFAULT 1"),
    ("cluster_method", "TEXT"),
    ("embedding", "BLOB"),
    ("image_url", "TEXT"),
    ("teaser", "TEXT"),
    ("relation", "TEXT"),        # null | standalone | reaction
    ("parent_item_id", "TEXT"),  # FK -> items.id, set when relation=reaction
)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema, for existing DBs."""
    cur = conn.execute("PRAGMA table_info(items)")
    existing = {row[1] for row in cur.fetchall()}
    for col, decl in _DEDUP_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {decl}")
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def dedup_key_for_url(url: str) -> str:
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()


def dedup_key_for_msg(message_id: str, title: str) -> str:
    seed = f"{message_id}|{(title or '').strip()}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


class ItemStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        # 1. Tables first (CREATE TABLE IF NOT EXISTS).
        self.conn.executescript(_TABLES_SCHEMA)
        self.conn.commit()
        # 2. ALTER TABLE for any post-1st-version columns missing on
        #    a pre-migration DB. New DBs already have them — no-op.
        _ensure_columns(self.conn)
        # 3. Indexes (some reference columns added in step 2).
        self.conn.executescript(_INDEXES_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ItemStore:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def has_dedup_key(self, dedup_key: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM items WHERE dedup_key = ? LIMIT 1", (dedup_key,)
        )
        return cur.fetchone() is not None

    def existing_dedup_keys(self, keys: list[str]) -> set[str]:
        """Return the subset of `keys` that already have rows in `items`.

        Chunked to stay under SQLite's parameter limit (default 999).
        """
        if not keys:
            return set()
        chunk_size = 500
        found: set[str] = set()
        for i in range(0, len(keys), chunk_size):
            chunk = keys[i : i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur = self.conn.execute(
                f"SELECT dedup_key FROM items WHERE dedup_key IN ({placeholders})",
                chunk,
            )
            for row in cur.fetchall():
                found.add(row[0])
        return found

    def insert_items(self, items: list[dict]) -> tuple[int, int]:
        """Insert items with INSERT OR IGNORE on dedup_key conflict.

        Returns (saved, skipped). Items must contain all unified-schema fields
        plus id + dedup_key (use normalize.py helpers).
        """
        saved = skipped = 0
        for item in items:
            try:
                cur = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO items (
                      id, dedup_key, source_id, source_channel, title, desp, date,
                      content, is_html, url, author, fetched_at, raw_meta, image_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["dedup_key"],
                        item["source_id"],
                        item["source_channel"],
                        item.get("title"),
                        item.get("desp"),
                        item.get("date"),
                        item.get("content"),
                        1 if item.get("is_html") else 0,
                        item.get("url"),
                        item.get("author"),
                        item["fetched_at"],
                        json.dumps(item.get("raw_meta") or {}, ensure_ascii=False),
                        item.get("image_url") or None,
                    ),
                )
                if cur.rowcount > 0:
                    saved += 1
                else:
                    skipped += 1
            except sqlite3.IntegrityError as exc:
                log.warning("Insert failed for dedup_key=%s: %s", item.get("dedup_key"), exc)
                skipped += 1
        self.conn.commit()
        return saved, skipped

    def start_run(self, channel: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (channel, started_at) VALUES (?, ?)",
            (channel, now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        ok: bool,
        fetched: int,
        saved: int,
        skipped: int,
        failed: int,
        errors: list[str],
    ) -> None:
        self.conn.execute(
            """
            UPDATE runs
               SET finished_at=?, ok=?, fetched=?, saved=?, skipped=?, failed=?, errors=?
             WHERE run_id=?
            """,
            (
                now_iso(),
                1 if ok else 0,
                fetched,
                saved,
                skipped,
                failed,
                json.dumps(errors, ensure_ascii=False),
                run_id,
            ),
        )
        self.conn.commit()

    def items_in_window(
        self,
        *,
        days: int,
        only_unclustered: bool = False,
        as_of: "datetime | None" = None,
    ) -> list[sqlite3.Row]:
        """Return items whose `date` falls in the last `days` days (UTC).

        If `only_unclustered`, restrict to rows with cluster_id IS NULL.
        Items without a parseable date fall back to fetched_at for the window.
        `as_of` overrides the reference point for the window (default: now).
        """
        from datetime import datetime, timedelta, timezone

        ref = as_of if as_of is not None else datetime.now(timezone.utc)
        cutoff = (ref - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        sql = (
            "SELECT id, dedup_key, source_id, source_channel, title, url, date, "
            "       fetched_at, content, cluster_id, is_primary, cluster_method, "
            "       embedding "
            "FROM items "
            "WHERE COALESCE(date, fetched_at) >= ?"
        )
        params: list = [cutoff]
        if only_unclustered:
            sql += " AND cluster_id IS NULL"
        sql += " ORDER BY COALESCE(date, fetched_at) DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def items_clustered_in_window(self, days: int) -> list[sqlite3.Row]:
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace(
            "+00:00", "Z"
        )
        sql = (
            "SELECT id, dedup_key, source_id, source_channel, title, url, date, "
            "       fetched_at, content, cluster_id, is_primary, cluster_method, "
            "       embedding "
            "FROM items "
            "WHERE COALESCE(date, fetched_at) >= ? AND cluster_id IS NOT NULL "
            "ORDER BY COALESCE(date, fetched_at) DESC"
        )
        return list(self.conn.execute(sql, [cutoff]).fetchall())

    def assign_cluster(
        self,
        item_id: str,
        cluster_id: str,
        is_primary: int,
        cluster_method: str | None,
    ) -> None:
        self.conn.execute(
            "UPDATE items SET cluster_id=?, is_primary=?, cluster_method=? WHERE id=?",
            (cluster_id, is_primary, cluster_method, item_id),
        )

    def get_embedding(self, item_id: str) -> bytes | None:
        row = self.conn.execute(
            "SELECT embedding FROM items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        return row["embedding"]

    def set_embedding(self, item_id: str, blob: bytes) -> None:
        self.conn.execute(
            "UPDATE items SET embedding=? WHERE id=?", (blob, item_id)
        )

    def items_needing_summary(self, *, limit: int = 100) -> list[sqlite3.Row]:
        """Primary items that have no AI summary yet, oldest first."""
        return list(self.conn.execute(
            """
            SELECT id, title, content, is_html, cluster_id, date, source_id, source_channel
            FROM items
            WHERE is_primary = 1 AND summary IS NULL AND content IS NOT NULL AND content != ''
            ORDER BY COALESCE(date, fetched_at) ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall())

    def set_enrichment(
        self,
        item_id: str,
        *,
        teaser: str,
        summary: str,
        importance: int,
        category: str,
    ) -> None:
        self.conn.execute(
            "UPDATE items SET teaser=?, summary=?, importance=?, category=? WHERE id=?",
            (teaser, summary, importance, category, item_id),
        )

    def cluster_members_content(
        self, cluster_id: str, *, exclude_id: str
    ) -> tuple[list[str], int]:
        """Return (content list of up to 2 non-primary members, total cluster size)."""
        rows = self.conn.execute(
            """
            SELECT content,
                   COUNT(*) OVER () AS total
            FROM items
            WHERE cluster_id = ? AND id != ? AND content IS NOT NULL
            ORDER BY LENGTH(content) DESC
            LIMIT 2
            """,
            (cluster_id, exclude_id),
        ).fetchall()
        total = rows[0]["total"] + 1 if rows else 1  # +1 for the primary
        return [r["content"] for r in rows], total

    def enriched_primary_items_for_date(self, target_date: date) -> list[sqlite3.Row]:
        """Enriched primary items (summary set) for a specific UTC calendar date."""
        date_str = target_date.isoformat()  # "2026-05-03"
        return list(self.conn.execute(
            """
            SELECT i.id, i.title, i.teaser, i.summary, i.importance, i.category,
                   i.url, i.source_id, i.date, i.image_url, i.cluster_id,
                   CASE
                     WHEN i.cluster_id IS NULL THEN 1
                     ELSE (SELECT COUNT(*) FROM items c WHERE c.cluster_id = i.cluster_id)
                   END AS cluster_size
            FROM items i
            WHERE i.is_primary = 1 AND i.summary IS NOT NULL
              AND date(COALESCE(i.date, i.fetched_at)) = ?
            ORDER BY i.importance DESC, COALESCE(i.date, i.fetched_at) DESC
            """,
            (date_str,),
        ).fetchall())

    def set_relation(
        self,
        item_id: str,
        relation: str,
        parent_item_id: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE items SET relation=?, parent_item_id=? WHERE id=?",
            (relation, parent_item_id, item_id),
        )

    def unlinked_twitter_items(self, days: int) -> list[sqlite3.Row]:
        """Twitter items within window that have not yet been relation-linked."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        return list(self.conn.execute(
            """
            SELECT id, source_id, source_channel, title, url, date, fetched_at,
                   content, embedding
            FROM items
            WHERE source_channel = 'twitter'
              AND relation IS NULL
              AND COALESCE(date, fetched_at) >= ?
            ORDER BY COALESCE(date, fetched_at) DESC
            """,
            (cutoff,),
        ).fetchall())

    def news_items_in_window(self, days: int) -> list[sqlite3.Row]:
        """RSS/Gmail items within window for relation matching."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        return list(self.conn.execute(
            """
            SELECT id, source_id, source_channel, title, url, date, fetched_at,
                   content, embedding
            FROM items
            WHERE source_channel IN ('rss', 'gmail')
              AND COALESCE(date, fetched_at) >= ?
            ORDER BY COALESCE(date, fetched_at) DESC
            """,
            (cutoff,),
        ).fetchall())

    def commit(self) -> None:
        self.conn.commit()

    def count_items(self, source_channel: str | None = None) -> int:
        if source_channel:
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE source_channel = ?", (source_channel,)
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM items")
        return int(cur.fetchone()[0])
