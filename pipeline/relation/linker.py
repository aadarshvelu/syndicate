"""Tweet-to-news relation linker.

For each unlinked twitter item, finds the closest news item (RSS/Gmail)
by embedding similarity. Classifies the relationship:

  standalone  — tweet predates the news, or no close news found
                (tweet IS the story / original take)
  reaction    — tweet posted after closely matching news item
                (tweet comments on existing story)

Idempotent: only processes items where relation IS NULL.
Uses cached embeddings from the dedup pipeline when available.
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
                news_rows = store.news_items_in_window(LINK_WINDOW_DAYS)

                if not tw_rows:
                    log.info("RelationLinker: no unlinked twitter items")
                    return result

                if not news_rows:
                    log.info("RelationLinker: no news items in window — marking all standalone")
                    for row in tw_rows:
                        store.set_relation(row["id"], "standalone")
                        result.standalone += 1
                    store.commit()
                    return result

                result.examined = len(tw_rows)
                log.info("RelationLinker: %d tweets x %d news items", len(tw_rows), len(news_rows))

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
                    vecs = semantic.embed_texts(texts)
                    for (idx, iid, _), vec in zip(needs_embed_news, vecs):
                        news_embs[idx] = vec
                        store.set_embedding(iid, semantic.serialize(vec))
                    store.commit()

                news_matrix = np.stack(news_embs)  # (N_news, dim)

                # Build/load embeddings for twitter items
                tw_vecs: list[np.ndarray] = []
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
                    vecs = semantic.embed_texts(texts)
                    for (idx, iid, _), vec in zip(needs_embed_tw, vecs):
                        tw_vecs[idx] = vec
                        store.set_embedding(iid, semantic.serialize(vec))
                    store.commit()

                # Score each tweet against all news items
                for row, tw_vec in zip(tw_rows, tw_vecs):
                    if tw_vec is None:
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

                    best_news = news_rows[best_idx]
                    tw_dt = _parse_dt(row["date"] or row["fetched_at"])
                    news_dt = _parse_dt(best_news["date"] or best_news["fetched_at"])

                    # Tweet predates news → it broke the story first → standalone
                    if tw_dt and news_dt and tw_dt < news_dt:
                        store.set_relation(row["id"], "standalone")
                        result.standalone += 1
                        log.debug(
                            "standalone/first-mover (sim=%.3f): tweet=%s news=%s",
                            best_sim, row["url"], best_news["url"],
                        )
                    else:
                        store.set_relation(row["id"], "reaction", parent_item_id=best_news["id"])
                        result.reactions += 1
                        log.debug(
                            "reaction (sim=%.3f): tweet=%s -> news=%s",
                            best_sim, row["url"], best_news["url"],
                        )

                store.commit()

        except Exception as exc:
            result.ok = False
            result.errors.append(f"{type(exc).__name__}: {exc}")
            log.exception("RelationLinker failed")

        log.info(
            "RelationLinker done: examined=%d standalone=%d reactions=%d",
            result.examined, result.standalone, result.reactions,
        )
        return result
