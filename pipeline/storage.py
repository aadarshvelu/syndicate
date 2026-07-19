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
from datetime import UTC, date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("db") / "snapshot.db"

# Tables only - runs first. Indexes that reference newer columns must wait
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
    ("relation", "TEXT"),  # null | standalone | reaction
    # FK -> items.id for the specific row matched at link time.
    ("parent_item_id", "TEXT"),
    # null means "not yet summarized"; non-null means "permanently skipped" with reason.
    # Gates items_needing_summary so banter/empty/reaction rows aren't re-processed.
    ("summarize_skip_reason", "TEXT"),
    # Cluster id of the matched news (the stable link, survives is_primary shifts and
    # cluster re-shuffles). Used by export to resolve to the current primary of that cluster.
    # null when no related news matched.
    ("parent_cluster_id", "TEXT"),
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
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        #    a pre-migration DB. New DBs already have them - no-op.
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
        cur = self.conn.execute("SELECT 1 FROM items WHERE dedup_key = ? LIMIT 1", (dedup_key,))
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
        as_of: datetime | None = None,
    ) -> list[sqlite3.Row]:
        """Return items whose `date` falls in the last `days` days (UTC).

        If `only_unclustered`, restrict to rows with cluster_id IS NULL.
        Items without a parseable date fall back to fetched_at for the window.
        `as_of` overrides the reference point for the window (default: now).
        """
        from datetime import datetime, timedelta

        ref = as_of if as_of is not None else datetime.now(UTC)
        cutoff = (ref - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        sql = (
            "SELECT id, dedup_key, source_id, source_channel, title, url, date, "
            "       fetched_at, content, cluster_id, is_primary, cluster_method, "
            "       embedding "
            "FROM items "
            "WHERE COALESCE(NULLIF(date, ''), fetched_at) >= ?"
        )
        params: list = [cutoff]
        if only_unclustered:
            sql += " AND cluster_id IS NULL"
        sql += " ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def items_clustered_in_window(self, days: int) -> list[sqlite3.Row]:
        from datetime import datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        sql = (
            "SELECT id, dedup_key, source_id, source_channel, title, url, date, "
            "       fetched_at, content, cluster_id, is_primary, cluster_method, "
            "       embedding "
            "FROM items "
            "WHERE COALESCE(NULLIF(date, ''), fetched_at) >= ? AND cluster_id IS NOT NULL "
            "ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC"
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
        row = self.conn.execute("SELECT embedding FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return None
        return row["embedding"]

    def set_embedding(self, item_id: str, blob: bytes) -> None:
        self.conn.execute("UPDATE items SET embedding=? WHERE id=?", (blob, item_id))

    def items_needing_summary(self, *, limit: int = 100) -> list[sqlite3.Row]:
        """Primary items that have no AI summary yet, NEWEST FIRST.

        Newest-first matters for two reasons:
          1. Today's items get summarized today and land in today's export
             JSON, surfacing fresh content in the PWA on the next run.
          2. When ingestion outpaces summarize throughput (e.g. 50/run cap
             vs 80 items/day arriving), the backlog naturally ages out -
             stale RSS items from weeks ago don't block fresh news.
        Old stragglers still get a chance once the fresh queue is empty.

        Columns must include everything the source-aware summarizers and the
        dispatcher in pipeline/AI/summarize.py read: image_url + raw_meta for
        the Twitter vision path, relation/parent_item_id for the reaction
        filter, and author for prompt context.
        """
        return list(
            self.conn.execute(
                """
            SELECT id, title, content, is_html, cluster_id, date, fetched_at,
                   source_id, source_channel, author, image_url, raw_meta,
                   relation, parent_item_id
            FROM items
            WHERE is_primary = 1
              AND summary IS NULL
              AND summarize_skip_reason IS NULL
              AND (
                  (content IS NOT NULL AND content != '')
                  OR (source_channel = 'twitter'
                      AND image_url IS NOT NULL AND image_url != '')
              )
            ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC
            LIMIT ?
            """,
                (limit,),
            ).fetchall()
        )

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

    def set_skip_reason(self, item_id: str, reason: str | None) -> None:
        """Mark an item as permanently skipped from summarization - or clear
        an existing mark by passing reason=None.

        Permanent skips (banter, empty content) are persisted so they don't
        re-enter items_needing_summary on every pipeline run. Passing None
        clears the column so the next run reconsiders the row - used when
        the linker promotes a previously-banter tweet to a reaction (the
        new code path will summarize it correctly).

        Transient failures (LM parse error, network exhaustion) leave this
        column null so the next run retries.
        """
        self.conn.execute(
            "UPDATE items SET summarize_skip_reason=? WHERE id=?",
            (reason, item_id),
        )

    def cluster_members_content(self, cluster_id: str, *, exclude_id: str) -> tuple[list[str], int]:
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
        return list(
            self.conn.execute(
                """
            SELECT i.id, i.title, i.teaser, i.summary, i.content,
                   i.importance, i.category,
                   i.url, i.source_id, i.source_channel, i.date, i.image_url,
                   i.cluster_id, i.relation, i.parent_item_id, i.parent_cluster_id,
                   i.author, i.raw_meta,
                   CASE
                     WHEN i.cluster_id IS NULL THEN 1
                     ELSE (SELECT COUNT(*) FROM items c WHERE c.cluster_id = i.cluster_id)
                   END AS cluster_size
            FROM items i
            WHERE i.is_primary = 1 AND i.summary IS NOT NULL
              AND date(COALESCE(NULLIF(i.date, ''), i.fetched_at)) = ?
            ORDER BY i.importance DESC, COALESCE(NULLIF(i.date, ''), i.fetched_at) DESC
            """,
                (date_str,),
            ).fetchall()
        )

    def set_relation(
        self,
        item_id: str,
        relation: str,
        parent_item_id: str | None = None,
        parent_cluster_id: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE items SET relation=?, parent_item_id=?, parent_cluster_id=? WHERE id=?",
            (relation, parent_item_id, parent_cluster_id, item_id),
        )

    def unlinked_twitter_items(self, days: int) -> list[sqlite3.Row]:
        """Twitter items within window that need (re-)linking.

        Two cohorts:
          - relation IS NULL: never been touched by the linker (newly ingested)
          - relation='standalone' AND parent_cluster_id IS NULL: was checked once
            but no matching news existed then. Re-evaluate in case news has
            arrived since. Once linked (parent_cluster_id IS NOT NULL) we
            never reconsider - the link is stable.
        """
        from datetime import datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        return list(
            self.conn.execute(
                """
            SELECT id, source_id, source_channel, title, url, date, fetched_at,
                   content, embedding
            FROM items
            WHERE source_channel = 'twitter'
              AND COALESCE(NULLIF(date, ''), fetched_at) >= ?
              AND (
                  relation IS NULL
                  OR (relation = 'standalone' AND parent_cluster_id IS NULL)
              )
            ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC
            """,
                (cutoff,),
            ).fetchall()
        )

    def news_items_in_window(self, days: int) -> list[sqlite3.Row]:
        """RSS/Gmail items within window for relation matching (all is_primary states)."""
        from datetime import datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        return list(
            self.conn.execute(
                """
            SELECT id, source_id, source_channel, title, url, date, fetched_at,
                   content, embedding, cluster_id
            FROM items
            WHERE source_channel IN ('rss', 'gmail')
              AND COALESCE(NULLIF(date, ''), fetched_at) >= ?
            ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC
            """,
                (cutoff,),
            ).fetchall()
        )

    def news_primary_items_in_window(self, days: int) -> list[sqlite3.Row]:
        """RSS/Gmail items within window - ONLY the primary copy of each cluster.

        Used by RelationLinker (run after Dedup) so tweets link to the canonical
        item in each cluster, not a soon-to-be-demoted duplicate. The returned
        row includes cluster_id so the linker can store parent_cluster_id directly.
        """
        from datetime import datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        return list(
            self.conn.execute(
                """
            SELECT id, source_id, source_channel, title, url, date, fetched_at,
                   content, embedding, cluster_id
            FROM items
            WHERE source_channel IN ('rss', 'gmail')
              AND is_primary = 1
              AND COALESCE(NULLIF(date, ''), fetched_at) >= ?
            ORDER BY COALESCE(NULLIF(date, ''), fetched_at) DESC
            """,
                (cutoff,),
            ).fetchall()
        )

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
