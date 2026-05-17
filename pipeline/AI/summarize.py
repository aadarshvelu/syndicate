"""AI-powered item enrichment — orchestrator for source-aware summarizers.

Configures a single LM via `pipeline.AI.lm.configure_lm()` (env-driven —
provider is selected by `AI_PROVIDER`), then dispatches each item to the
right `BaseSummarizer` subclass based on `source_channel`.

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
from pipeline.AI.lm import configure_lm
from pipeline.AI.rss_summarizer import RssSummarizer
from pipeline.AI.twitter_summarizer import TwitterSummarizer
from pipeline.budget import BudgetWatch
from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)

COMMIT_EVERY = 10

# Circuit breaker: if this many consecutive items fail with provider-like
# errors (network down, timeout, 5xx), assume the AI provider is unhealthy
# and bail. Without this, a dead Ollama causes the loop to iterate the full
# --limit (50–100 items) each producing the same connection error, wasting
# ~15 minutes per dead run.
_BREAKER_THRESHOLD = 5

# Exception class name substrings that indicate "the provider, not the item,
# is the problem". Match by name so we don't have to import litellm /
# anthropic / openai exception types here. Per-item parse failures (bad LM
# output, etc.) are not in this list — they don't count toward the breaker.
_PROVIDER_ERROR_HINTS = (
    "APIConnectionError",
    "ConnectionError",
    "Timeout",
    "TimeoutError",
    "ServiceUnavailableError",
    "InternalServerError",
    "BadGateway",
    "OllamaError",
)


def _is_provider_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    return any(hint in name for hint in _PROVIDER_ERROR_HINTS)

__all__ = [
    "SummarizePipeline",
    "SummarizeResult",
    "ItemSummary",
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

        consecutive_provider_failures = 0
        breaker_tripped = False
        budget = BudgetWatch.for_stage("summarize")
        budget_tripped = False

        try:
            with ItemStore(self.db_path) as store:
                items = store.items_needing_summary(limit=limit)
                result.examined = len(items)
                log.info(
                    "Summarize: %d items to process (budget=%.0fs)",
                    result.examined, budget.budget_seconds,
                )

                for i, row in enumerate(items):
                    if breaker_tripped or budget_tripped:
                        # Provider is unhealthy OR we've burned through the
                        # wall-clock budget — don't waste time on remaining
                        # items. Leave them alone (no skip_reason set) so the
                        # next run picks them up cleanly.
                        result.skipped += 1
                        continue

                    if budget.exceeded():
                        budget_tripped = True
                        remaining = result.examined - i
                        budget.log_exceeded(remaining_items=remaining)
                        result.errors.append(
                            f"budget_exceeded: summarize {budget.elapsed():.0f}s "
                            f">= {budget.budget_seconds:.0f}s; {remaining} item(s) deferred"
                        )
                        result.skipped += 1
                        continue
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
                        # Any successful call resets the breaker counter, even
                        # if the result is a skip (banter/empty). What matters
                        # is that the provider responded coherently.
                        consecutive_provider_failures = 0
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

                        if _is_provider_error(exc):
                            consecutive_provider_failures += 1
                            if consecutive_provider_failures >= _BREAKER_THRESHOLD:
                                breaker_tripped = True
                                remaining = result.examined - (i + 1)
                                log.error(
                                    "Summarize circuit breaker tripped: %d consecutive "
                                    "provider errors (last: %s). Skipping remaining %d item(s) — "
                                    "they'll be retried next run.",
                                    consecutive_provider_failures,
                                    type(exc).__name__,
                                    remaining,
                                )
                                result.errors.append(
                                    f"circuit_breaker: {consecutive_provider_failures} "
                                    f"consecutive {type(exc).__name__}; "
                                    f"{remaining} item(s) deferred"
                                )
                        else:
                            # Per-item content/parse failure — doesn't indicate
                            # provider health. Reset so we don't trip on a
                            # cluster of malformed items.
                            consecutive_provider_failures = 0
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
