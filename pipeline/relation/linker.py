"""Tweet-to-news relation linker.

For each (re-)linkable twitter item, finds the closest PRIMARY news item
(RSS/Gmail with is_primary=1) by embedding similarity. Classifies the
relationship using (relation, parent_cluster_id) pair:

  ('reaction',   cluster_id)  — tweet posted AFTER matching news (reacts to it)
  ('standalone', cluster_id)  — tweet posted BEFORE matching news (scoop)
  ('standalone', null)        — no close news found

This pipeline stage MUST run after Dedup so every news row in window has
its final cluster_id set. We store cluster_id (not the matched row id) as
the stable link — cluster ids are immutable once persisted, even when the
primary inside a cluster shifts on future runs.

Linker is run on two cohorts (via `unlinked_twitter_items`):
  - relation IS NULL                                  → new tweets
  - relation='standalone' AND parent_cluster_id IS NULL → orphans whose
    matching news may have arrived since the prior run

Already-linked tweets (parent_cluster_id IS NOT NULL) are NEVER reconsidered.
No flip-flop possible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from pipeline.storage import DEFAULT_DB_PATH, ItemStore

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.72
LINK_WINDOW_DAYS = 7


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class RelationResult:
    ok: bool
    examined: int = 0
    standalone: int = 0
    reactions: int = 0
    errors: list[str] = field(default_factory=list)


class RelationLinker:
    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def run(self) -> RelationResult:
        from pipeline.dedup import semantic

        result = RelationResult(ok=True)

        try:
            with ItemStore(self._db_path) as store:
                tw_rows = store.unlinked_twitter_items(LINK_WINDOW_DAYS)
                news_rows = store.news_primary_items_in_window(LINK_WINDOW_DAYS)

                if not tw_rows:
                    log.info("RelationLinker: no twitter items needing (re-)linking")
                    return result

                if not news_rows:
                    log.info("RelationLinker: no primary news in window — marking all standalone")
                    for row in tw_rows:
                        store.set_relation(row["id"], "standalone")
                        result.standalone += 1
                    store.commit()
                    return result

                result.examined = len(tw_rows)
                log.info(
                    "RelationLinker: %d tweet(s) x %d primary news item(s)",
                    len(tw_rows), len(news_rows),
                )

                # Build/load embeddings for news items
                news_embs: list[np.ndarray] = []
                needs_embed_news: list[tuple[int, str, str]] = []

                for idx, row in enumerate(news_rows):
                    blob = row["embedding"]
                    if blob:
                        news_embs.append(semantic.deserialize(blob))
                    else:
                        needs_embed_news.append((idx, row["id"], semantic.text_for_embedding(dict(row))))
                        news_embs.append(None)  # placeholder

                if needs_embed_news:
                    texts = [t for _, _, t in needs_embed_news]
                    # Batch embeds in chunks to bound memory on large first runs.
                    BATCH = 256
                    vecs: list[np.ndarray] = []
                    for i in range(0, len(texts), BATCH):
                        vecs.extend(semantic.embed_texts(texts[i:i + BATCH]))
                    for (idx, iid, _), vec in zip(needs_embed_news, vecs):
                        news_embs[idx] = vec
                        store.set_embedding(iid, semantic.serialize(vec))
                    store.commit()

                # Drop any placeholders left over from failed embedding (defensive)
                valid_news: list[tuple[np.ndarray, dict]] = [
                    (e, dict(news_rows[i])) for i, e in enumerate(news_embs) if e is not None
                ]
                if not valid_news:
                    log.warning("RelationLinker: no usable news embeddings — marking all standalone")
                    for row in tw_rows:
                        store.set_relation(row["id"], "standalone")
                        result.standalone += 1
                    store.commit()
                    return result

                news_matrix = np.stack([e for e, _ in valid_news])  # (N_news, dim)
                valid_news_rows = [r for _, r in valid_news]

                # Build/load embeddings for twitter items (same batching pattern)
                tw_vecs: list[np.ndarray | None] = []
                needs_embed_tw: list[tuple[int, str, str]] = []

                for idx, row in enumerate(tw_rows):
                    blob = row["embedding"]
                    if blob:
                        tw_vecs.append(semantic.deserialize(blob))
                    else:
                        needs_embed_tw.append((idx, row["id"], semantic.text_for_embedding(dict(row))))
                        tw_vecs.append(None)

                if needs_embed_tw:
                    texts = [t for _, _, t in needs_embed_tw]
                    BATCH = 256
                    vecs = []
                    for i in range(0, len(texts), BATCH):
                        vecs.extend(semantic.embed_texts(texts[i:i + BATCH]))
                    for (idx, iid, _), vec in zip(needs_embed_tw, vecs):
                        tw_vecs[idx] = vec
                        store.set_embedding(iid, semantic.serialize(vec))
                    store.commit()

                # Score each tweet against all primary news items. The transaction
                # at this loop guarantees: if interrupted, partial relation
                # updates are rolled back — next run reprocesses cleanly.
                store.conn.execute("BEGIN")
                try:
                    for row, tw_vec in zip(tw_rows, tw_vecs):
                        if tw_vec is None:
                            # embedding failed — leave as standalone, retry next run via re-eval
                            store.set_relation(row["id"], "standalone")
                            result.standalone += 1
                            continue

                        sims = news_matrix @ tw_vec  # dot product = cosine (unit vecs)
                        best_idx = int(np.argmax(sims))
                        best_sim = float(sims[best_idx])

                        if best_sim < SIMILARITY_THRESHOLD:
                            store.set_relation(row["id"], "standalone")
                            result.standalone += 1
                            log.debug("standalone (sim=%.3f): %s", best_sim, row["url"])
                            continue

                        best_news = valid_news_rows[best_idx]

                        # If the matched news has no cluster_id (e.g. dedup crashed
                        # earlier this run, or a news source was added without going
                        # through dedup), we can't write a stable link. Fall back to
                        # standalone-no-parent and log — the row stays in the orphan
                        # cohort so the next run re-evaluates once cluster_id exists.
                        matched_cluster_id = best_news.get("cluster_id")
                        if not matched_cluster_id:
                            log.warning(
                                "Matched news has no cluster_id; "
                                "falling back to standalone (sim=%.3f tweet=%s news=%s)",
                                best_sim, row["url"], best_news["url"],
                            )
                            store.set_relation(row["id"], "standalone")
                            result.standalone += 1
                            continue

                        # Strict date validation: never fall back to fetched_at for
                        # the scoop/reaction decision. fetched_at is ingestion time,
                        # not author wallclock — mixing them flips scoop classification
                        # wrongly when news is ingested fresh against an old tweet.
                        tw_dt = _parse_dt(row["date"])
                        news_dt = _parse_dt(best_news.get("date"))

                        if tw_dt is None or news_dt is None:
                            # Without both authoritative dates, we know the link
                            # exists but can't classify scoop vs reaction. Default
                            # to standalone but persist the cluster link.
                            store.set_relation(
                                row["id"], "standalone",
                                parent_item_id=best_news["id"],
                                parent_cluster_id=matched_cluster_id,
                            )
                            # A previously-banter classification was made when this
                            # tweet looked unrelated. Now that it's tied to news,
                            # let the new code path re-summarize it.
                            store.set_skip_reason(row["id"], None)
                            result.standalone += 1
                            log.debug(
                                "standalone/no-date (sim=%.3f): tweet=%s news=%s",
                                best_sim, row["url"], best_news["url"],
                            )
                        elif tw_dt < news_dt:
                            # Tweet predates news → scoop. Standalone, but captures
                            # the link so frontend can render a "first reported by" badge.
                            store.set_relation(
                                row["id"], "standalone",
                                parent_item_id=best_news["id"],
                                parent_cluster_id=matched_cluster_id,
                            )
                            store.set_skip_reason(row["id"], None)
                            result.standalone += 1
                            log.debug(
                                "standalone/scoop (sim=%.3f): tweet=%s news=%s",
                                best_sim, row["url"], best_news["url"],
                            )
                        else:
                            # Tweet posted after the news → reaction.
                            store.set_relation(
                                row["id"], "reaction",
                                parent_item_id=best_news["id"],
                                parent_cluster_id=matched_cluster_id,
                            )
                            # Clear any stale banter mark — reaction route via the
                            # new TwitterSummarizer (classifier-skipped) will now
                            # produce a real summary.
                            store.set_skip_reason(row["id"], None)
                            result.reactions += 1
                            log.debug(
                                "reaction (sim=%.3f): tweet=%s -> news=%s",
                                best_sim, row["url"], best_news["url"],
                            )
                    store.conn.commit()
                except Exception:
                    store.conn.rollback()
                    raise

        except Exception as exc:
            result.ok = False
            result.errors.append(f"{type(exc).__name__}: {exc}")
            log.exception("RelationLinker failed")

        log.info(
            "RelationLinker done: examined=%d standalone=%d reactions=%d",
            result.examined, result.standalone, result.reactions,
        )
        return result
