"""AI-powered item enrichment — orchestrator for source-aware summarizers.

Configures a single LM via `pipeline.AI.lm.configure_lm()` (env-driven; today
Ollama, swap provider in one place), then dispatches each item to the right
`BaseSummarizer` subclass based on `source_channel`.

Storage contract is unchanged: same four columns are written via
`set_enrichment(teaser, summary, importance, category)`.

To add a new source: implement a subclass of `BaseSummarizer` and register it
in `_build_summarizers()`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.AI.base import BaseSummarizer, ItemSummary
from pipeline.AI.lm import DEFAULT_OLLAMA_MODEL, configure_lm
from pipeline.AI.rss_summarizer import RssSummarizer
from pipeline.AI.twitter_summarizer import TwitterSummarizer
from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)

COMMIT_EVERY = 10

# Backwards-compatible alias for callers that imported DEFAULT_MODEL from here.
DEFAULT_MODEL = DEFAULT_OLLAMA_MODEL

__all__ = [
    "SummarizePipeline",
    "SummarizeResult",
    "ItemSummary",
    "DEFAULT_MODEL",
]


@dataclass
class SummarizeResult:
    channel: str = "summarize"
    started_at: str = ""
    finished_at: str = ""
    examined: int = 0
    summarized: int = 0
    skipped: int = 0
    ok: bool = True
    errors: list[str] = field(default_factory=list)


class SummarizePipeline:
    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        model: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        # `model` is a per-run override that wins over env vars in lm.configure_lm.
        self.model_override = model

    def _build_summarizers(self) -> dict[str, BaseSummarizer]:
        """Map source_channel → summarizer instance.

        Add new channels here. Sharing a class across channels (RSS + Gmail
        both use RssSummarizer) is fine.
        """
        return {
            "rss":     RssSummarizer(),
            "gmail":   RssSummarizer(),
            "twitter": TwitterSummarizer(),
        }

    def run(self, *, limit: int = 100) -> SummarizeResult:
        result = SummarizeResult(started_at=now_iso())

        # Configure the global LM ONCE before any predictor runs. The provider
        # is selected by the AI_PROVIDER env var; today it's Ollama, tomorrow
        # swap to anthropic/openai by changing the env (and key).
        try:
            configure_lm(model_override=self.model_override)
        except Exception as exc:
            result.ok = False
            result.errors.append(f"configure_lm: {exc}")
            log.exception("Failed to configure LM")
            result.finished_at = now_iso()
            return result

        summarizers = self._build_summarizers()

        try:
            with ItemStore(self.db_path) as store:
                items = store.items_needing_summary(limit=limit)
                result.examined = len(items)
                log.info("Summarize: %d items to process", result.examined)

                for i, row in enumerate(items):
                    item = dict(row)
                    # raw_meta is stored as JSON text — parse it once here so
                    # every summarizer sees a dict (and not a JSON string).
                    rm = item.get("raw_meta")
                    if isinstance(rm, str):
                        try:
                            item["raw_meta"] = json.loads(rm) if rm else {}
                        except json.JSONDecodeError as exc:
                            log.warning(
                                "raw_meta JSON parse failed for %s (%s); using {}: %s",
                                item.get("id", "?")[:8], type(exc).__name__,
                                (rm or "")[:80],
                            )
                            item["raw_meta"] = {}
                    elif rm is None:
                        item["raw_meta"] = {}
                    title_short = (item.get("title") or item.get("url") or "")[:60]

                    # Reactions used to be short-circuited here (skip_reason='reaction').
                    # That was wrong — it threw away useful content. They're now
                    # first-class feed items: TwitterSummarizer skips the banter
                    # classifier when item.relation == 'reaction' and goes straight
                    # to summary, with the cluster link preserved via parent_cluster_id.

                    channel = item.get("source_channel") or ""
                    summarizer = summarizers.get(channel)
                    if summarizer is None:
                        log.warning(
                            "[%d/%d] no summarizer registered for source_channel=%r; skipping %s",
                            i + 1, result.examined, channel, title_short,
                        )
                        result.skipped += 1
                        continue

                    cluster_id = item.get("cluster_id")
                    member_contents: list[str] = []
                    cluster_size = 1
                    if cluster_id:
                        member_contents, cluster_size = store.cluster_members_content(
                            cluster_id, exclude_id=item["id"]
                        )

                    try:
                        out = summarizer.summarize(
                            item,
                            cluster_size=cluster_size,
                            member_contents=member_contents,
                        )
                    except Exception as exc:
                        # predict_with_retry already retried network errors;
                        # anything reaching here is unrecoverable for this item.
                        log.warning(
                            "[%d/%d] %s crashed for %r: %s",
                            i + 1, result.examined,
                            type(summarizer).__name__, title_short, exc,
                        )
                        result.errors.append(
                            f"{type(summarizer).__name__}({title_short}): {exc}"
                        )
                        result.skipped += 1
                        continue

                    if out.skip_reason:
                        # Permanent skip — persist the reason so we never
                        # re-process this row (banter, empty_content, etc.).
                        store.set_skip_reason(item["id"], out.skip_reason)
                        result.skipped += 1
                        continue

                    if out.summary is None:
                        # Transient failure — leave the row alone, retry next run.
                        result.skipped += 1
                        continue

                    summary_obj = out.summary

                    if not summary_obj.teaser or not summary_obj.summary:
                        log.warning(
                            "[%d/%d] empty teaser/summary for %s; skipping",
                            i + 1, result.examined, title_short,
                        )
                        result.skipped += 1
                        continue

                    importance = (
                        min(5, summary_obj.importance + 1) if cluster_size >= 3 else summary_obj.importance
                    )

                    store.set_enrichment(
                        item["id"],
                        teaser=summary_obj.teaser,
                        summary=summary_obj.summary,
                        importance=importance,
                        category=summary_obj.category,
                    )
                    result.summarized += 1
                    log.info(
                        "[%d/%d] %s | imp=%d cat=%s",
                        i + 1, result.examined,
                        title_short, importance, summary_obj.category,
                    )

                    if (i + 1) % COMMIT_EVERY == 0:
                        store.commit()

                store.commit()

        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
            result.ok = False
            log.exception("SummarizePipeline crashed")

        result.finished_at = now_iso()
        return result
