"""One-time backfill for the "reactions as first-class items" change.

Scope: only items where COALESCE(date, fetched_at) >= now - 2 days. Older
rows are already in historical JSON files in news-archive that don't get
re-exported, so backfilling them produces no user-visible benefit.

Three operations, all idempotent:

  1. Derive parent_cluster_id from existing parent_item_id (for reactions
     that were linked under the old code path before the column existed).
  2. Clear stuck `summarize_skip_reason` ('reaction' or 'banter') on
     reactions so the new code path can summarize them.
  3. Run the summarize pipeline in small batches so re-summarization
     doesn't stall a regular pipeline run.

Re-runnable safely: SQL guards on IS NULL / IN(...) make re-application
a no-op.

Usage:
    uv run python -m scripts.backfill_reactions
    uv run python -m scripts.backfill_reactions --dry-run
    uv run python -m scripts.backfill_reactions --batch 20 --no-summarize
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from pipeline.AI.summarize import SummarizePipeline  # noqa: E402
from pipeline.storage import DEFAULT_DB_PATH, ItemStore  # noqa: E402

log = logging.getLogger("backfill_reactions")


_SQL_DERIVE_PARENT_CLUSTER_ID = """
UPDATE items AS t
SET parent_cluster_id = (
    SELECT cluster_id FROM items WHERE id = t.parent_item_id
)
WHERE t.source_channel = 'twitter'
  AND t.parent_item_id IS NOT NULL
  AND t.parent_cluster_id IS NULL
  AND COALESCE(t.date, t.fetched_at) >= date('now', '-2 days');
"""

_SQL_CLEAR_STUCK_SKIP_REASON = """
UPDATE items
SET summarize_skip_reason = NULL
WHERE source_channel = 'twitter'
  AND relation = 'reaction'
  AND summarize_skip_reason IN ('reaction', 'banter')
  AND COALESCE(date, fetched_at) >= date('now', '-2 days');
"""

_SQL_INSPECT_SCOPE = """
SELECT
    SUM(CASE WHEN parent_item_id IS NOT NULL AND parent_cluster_id IS NULL
             THEN 1 ELSE 0 END)                AS will_derive_cluster_id,
    SUM(CASE WHEN relation = 'reaction'
             AND summarize_skip_reason IN ('reaction', 'banter')
             THEN 1 ELSE 0 END)                AS will_clear_skip_reason,
    SUM(CASE WHEN relation = 'standalone'
             AND summarize_skip_reason = 'banter'
             AND parent_cluster_id IS NULL
             THEN 1 ELSE 0 END)                AS banter_standalones_in_scope
FROM items
WHERE source_channel = 'twitter'
  AND COALESCE(date, fetched_at) >= date('now', '-2 days');
"""


def run(db_path: Path, *, dry_run: bool, batch_size: int, do_summarize: bool) -> int:
    with ItemStore(db_path) as store:
        cur = store.conn.execute(_SQL_INSPECT_SCOPE)
        derive, clear, banter_std = cur.fetchone()
        log.info(
            "Scope (last 2 days, twitter):  derive_cluster_id=%d  clear_skip_reason=%d  "
            "banter_standalones_waiting_for_linker=%d",
            derive or 0, clear or 0, banter_std or 0,
        )

        if dry_run:
            log.info("Dry run — no changes will be made.")
            return 0

        log.info("Step 1/3: derive parent_cluster_id from parent_item_id …")
        cur = store.conn.execute(_SQL_DERIVE_PARENT_CLUSTER_ID)
        log.info("  → %d row(s) updated", cur.rowcount)

        log.info("Step 2/3: clear stuck summarize_skip_reason …")
        cur = store.conn.execute(_SQL_CLEAR_STUCK_SKIP_REASON)
        log.info("  → %d row(s) updated", cur.rowcount)

        store.commit()

    if not do_summarize:
        log.info("Skipping step 3 (--no-summarize). Re-run with --do-summarize to finish.")
        return 0

    log.info("Step 3/3: re-summarize cleared rows in batches of %d", batch_size)
    total_done = 0
    iteration = 0
    while True:
        iteration += 1
        result = SummarizePipeline(db_path=db_path).run(limit=batch_size)
        log.info(
            "  batch %d: examined=%d summarized=%d skipped=%d",
            iteration, result.examined, result.summarized, result.skipped,
        )
        total_done += result.summarized
        if result.examined == 0:
            break
        if iteration > 20:
            log.warning("Stopping after 20 batches; re-run if more remain.")
            break

    log.info("Done. %d total rows summarized across %d batch(es).", total_done, iteration)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print scope counts and exit (no writes)")
    parser.add_argument("--batch", type=int, default=20,
                        help="Items per summarize batch (default 20)")
    parser.add_argument("--no-summarize", action="store_true",
                        help="Run SQL steps only; skip the summarize batches")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet the noisy libs.
    for n in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(n).setLevel(logging.WARNING)

    return run(
        Path(args.db),
        dry_run=args.dry_run,
        batch_size=args.batch,
        do_summarize=not args.no_summarize,
    )


if __name__ == "__main__":
    sys.exit(main())
