"""Summarizer for RSS and Gmail items — long-form articles.

Single DSPy ChainOfThought call producing the full ItemSummary. Cluster-aware:
when the item's dedup cluster has >1 member, sibling contents are concatenated
into the prompt so the model can reconcile multiple sources into one summary.

Uses the globally-configured LM (see `pipeline.AI.lm.configure_lm`).

NOTE: This module deliberately does NOT use `from __future__ import annotations`.
DSPy's signature class resolves typed fields at class-definition time, but
`ChainOfThought` later rebuilds the signature via `signature.prepend(...)`
which doesn't carry the resolution context — string-form annotations would
re-appear as ForwardRefs and crash with
"Field types must be types, but received: ForwardRef(...)".
"""

import logging

import dspy
from pydantic import ValidationError

from pipeline.AI.base import (
    BaseSummarizer,
    ItemSummary,
    SummaryOutcome,
    build_content_with_cluster,
    predict_with_retry,
)
from pipeline.clean import for_llm

log = logging.getLogger(__name__)


class _NewsSummary(dspy.Signature):
    """Analyze a news article and return a structured summary.

    - key_facts: up to 8 verbatim facts (names, orgs, numbers, dates, key claims)
    - teaser: ≤150 chars, one compelling hook using the most surprising fact
    - summary: ≤450 chars, inverted pyramid; explain jargon once; include all key_facts
    - importance: integer 1-5 (5=major breaking news, 1=routine/minor)
    - category: pick the best fit from the allowed list
    """
    title: str = dspy.InputField(desc="Article headline (may be empty)")
    article: str = dspy.InputField(desc="Article body text")
    source_count: int = dspy.InputField(
        desc="Number of distinct sources in this dedup cluster (1 = single source)"
    )
    summary: ItemSummary = dspy.OutputField()


class RssSummarizer(BaseSummarizer):
    """Article-style summarization for RSS and Gmail newsletter items."""

    def __init__(self) -> None:
        # Predictor uses dspy.settings.lm at call time, so it's safe to construct
        # before configure_lm() has been called.
        self._predict = dspy.ChainOfThought(_NewsSummary)

    def summarize(
        self,
        item: dict,
        *,
        cluster_size: int = 1,
        member_contents: list[str] | None = None,
    ) -> SummaryOutcome:
        raw_content = item.get("content") or ""
        if not raw_content.strip():
            log.debug("RssSummarizer: empty content; permanent skip %s", item.get("id"))
            return SummaryOutcome.skip("empty_content")

        primary = for_llm(raw_content, is_html=bool(item.get("is_html")))
        members = member_contents or []
        article = build_content_with_cluster(primary, members)
        title = (item.get("title") or "").strip()

        try:
            pred = predict_with_retry(
                self._predict,
                title=title,
                article=article,
                source_count=cluster_size,
            )
            return SummaryOutcome.ok(pred.summary)
        except (ValidationError, ValueError) as exc:
            # Bad LM output is transient — retry next run, model may behave better.
            log.warning(
                "RssSummarizer parse/validate failed for %r: %s",
                title[:60] or item.get("id"), exc,
            )
            return SummaryOutcome.transient()
        except Exception as exc:
            # Retries already exhausted by predict_with_retry — give up for this run.
            log.warning(
                "RssSummarizer failed for %r (%s): %s",
                title[:60] or item.get("id"), type(exc).__name__, exc,
            )
            return SummaryOutcome.transient()
