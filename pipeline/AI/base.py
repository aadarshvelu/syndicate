"""Shared summarizer infrastructure: ABC, output schema, DSPy retry helper.

All summarizers produce the same `ItemSummary` shape — the storage contract
(`set_enrichment` columns: teaser/summary/importance/category) is fixed.
Subclasses differ only in HOW they prompt and whether they multi-step.

The actual LM is configured globally via `pipeline.AI.lm.configure_lm()`.
This file is provider-agnostic — no Ollama, no LiteLLM, no httpx specifics.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Callable, Literal, get_args

from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

Category = Literal[
    "ai_research", "ai_products", "economics",
    "policy", "startup", "world_news", "tech_news", "other",
]

CATEGORIES: list[str] = list(get_args(Category))


class ItemSummary(BaseModel):
    """The unified output every summarizer must produce. Stored shape unchanged."""
    key_facts: list[str] = Field(default_factory=list)
    teaser: str
    summary: str
    importance: int = Field(ge=1, le=5)
    category: Category


@dataclass(frozen=True)
class SummaryOutcome:
    """What a summarizer returns. Three states, distinguished structurally:

      - success      → summary set, skip_reason None  (write enrichment row)
      - permanent    → summary None, skip_reason set  (write skip_reason; never re-process)
      - transient    → both None                      (do nothing; retry next run)

    Use the factory methods (.ok / .skip / .transient) at construction sites
    so the intent is explicit. The dispatcher branches on these states in
    pipeline/AI/summarize.py.
    """
    summary: ItemSummary | None = None
    skip_reason: str | None = None

    @classmethod
    def ok(cls, summary: ItemSummary) -> "SummaryOutcome":
        return cls(summary=summary)

    @classmethod
    def skip(cls, reason: str) -> "SummaryOutcome":
        return cls(skip_reason=reason)

    @classmethod
    def transient(cls) -> "SummaryOutcome":
        return cls()


# ── retry helper for DSPy / LiteLLM calls ─────────────────────────────────────
#
# DSPy delegates to LiteLLM for the actual HTTP. Network and rate-limit failures
# can surface as several different exception types depending on provider:
# litellm.APIConnectionError, litellm.Timeout, litellm.RateLimitError, plain
# httpx exceptions, etc. Rather than couple to provider-specific classes, we
# match by name + message. False positives only mean an extra retry; real bugs
# still surface after attempt 3.
#
# ValidationError is also retried — LM output is non-deterministic, and a
# fresh sampling will often produce a parseable JSON on attempt 2 or 3.

_RETRIABLE_NAMES = {
    "APIConnectionError",
    "Timeout",
    "TimeoutException",
    "RateLimitError",
    "ServiceUnavailableError",
    "InternalServerError",
    "NetworkError",
    "RemoteProtocolError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "ValidationError",   # Pydantic — LM emitted JSON missing/wrong-typed required fields
}


def _is_retriable(exc: BaseException) -> bool:
    if type(exc).__name__ in _RETRIABLE_NAMES:
        return True
    msg = str(exc).lower()
    return (
        "connection" in msg
        or "timeout" in msg
        or "rate limit" in msg
        or "temporarily unavailable" in msg
    )


def _log_before_retry(retry_state) -> None:
    """tenacity before_sleep callback. Differentiates ValidationError (LM gave
    bad JSON) from network/rate failures so the log clearly shows WHICH kind of
    transient is firing."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    cls = type(exc).__name__ if exc else "?"
    sleep = retry_state.next_action.sleep if retry_state.next_action else 0.0
    msg = str(exc).replace("\n", " ")[:300] if exc else ""
    if cls == "ValidationError":
        log.warning(
            "ValidationError on attempt %d/3 — LM output didn't validate; "
            "retrying in %.1fs: %s",
            retry_state.attempt_number, sleep, msg,
        )
    else:
        log.warning(
            "Transient %s on attempt %d/3, retrying in %.1fs: %s",
            cls, retry_state.attempt_number, sleep, msg,
        )


def predict_with_retry(predictor: Callable, /, **inputs):
    """Call a DSPy predictor with retry on transient network / rate-limit /
    LM-validation errors.

    3 attempts, exponential backoff 1-8s. ValidationError is retried because
    LM output is stochastic — a fresh sample often produces valid JSON.
    Anything not in `_RETRIABLE_NAMES` propagates to the caller, which
    typically catches and skips that item.
    """
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retriable),
        before_sleep=_log_before_retry,
        reraise=True,
    )
    def _call():
        return predictor(**inputs)
    return _call()


def build_content_with_cluster(primary: str, members: list[str]) -> str:
    """Concatenate the primary content with non-empty cluster siblings.

    No length cap — modern models (gemma4 / Claude / GPT) have context windows
    far larger than any plausible article cluster. If a future model needs
    truncation, do it at the LM layer (max_tokens / max_input), not here.
    """
    parts = [primary] + [m for m in members if m]
    return "\n\n---\n\n".join(parts)


class BaseSummarizer(abc.ABC):
    """Maps an item dict → SummaryOutcome.

    Subclasses encapsulate source-specific prompt strategy (single-call article
    summary, classify-then-summarize for tweets, vision input, etc.) but share:
      - the global LM configured via `pipeline.AI.lm.configure_lm()`
      - retry semantics through `predict_with_retry`
      - the unified output schema (`ItemSummary`)

    Outcome semantics — pick one of the three factory methods:
      - SummaryOutcome.ok(item_summary): success; dispatcher writes enrichment.
      - SummaryOutcome.skip(reason): permanent skip (banter, empty content, etc.);
        dispatcher persists the reason so the row is never re-processed.
      - SummaryOutcome.transient(): retriable failure (LM parse error, network
        exhaustion); dispatcher leaves the row alone for the next run.

    Raise an exception only for unrecoverable bugs. The dispatcher catches
    exceptions and treats them as transient. Retriable network errors are
    already retried inside `predict_with_retry`.
    """

    @abc.abstractmethod
    def summarize(
        self,
        item: dict,
        *,
        cluster_size: int = 1,
        member_contents: list[str] | None = None,
    ) -> SummaryOutcome:
        ...
