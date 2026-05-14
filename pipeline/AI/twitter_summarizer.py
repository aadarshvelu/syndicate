"""Summarizer for Twitter items — classify first, then summarize (with image if any).

Three DSPy signatures, two-step pipeline:

  1. ClassifyTweet → 'news' | 'info' | 'banter'.
     If 'banter' → return None (drop, don't summarize).

  2. Summarize. Two variants share the same `ItemSummary` output schema:
       - `_SummarizeTweet`           text only
       - `_SummarizeTweetWithImage`  same + a `dspy.Image` input

     Image handling: we always pre-download the image and pass it as a base64
     data URI. Cloud providers accept this happily, and Ollama via LiteLLM
     can't fetch URLs server-side — so this is the portable path.

Reactions (`relation == 'reaction'`) are filtered at the dispatcher level in
`summarize.py`; this summarizer should never see them.

NOTE: This module deliberately does NOT use `from __future__ import annotations`.
DSPy's `ChainOfThought` rebuilds the signature via `signature.prepend(...)`,
which loses the resolution context for stringified annotations. Concrete
types (`ItemSummary`, `dspy.Image`, `Literal[...]`) keep DSPy happy.
"""

import base64
import logging
from typing import Literal

import dspy
import httpx
from pydantic import ValidationError

from pipeline.AI.base import (
    BaseSummarizer,
    ItemSummary,
    SummaryOutcome,
    predict_with_retry,
)

log = logging.getLogger(__name__)


# ── DSPy signatures ───────────────────────────────────────────────────────────

class _ClassifyTweet(dspy.Signature):
    """Classify a tweet by its informational value to a news-feed reader.

    - news: reports a new event, announcement, finding, product launch, or
      breaking development.
    - info: factual / educational / insight content with standalone value
      (deep takes, technical explainers, useful threads). Not breaking, but
      worth reading.
    - banter: personal, joke, low-context reaction, or noise without standalone
      value.

    Reposts and quote-tweets must be classified by the underlying content's
    value to the reader, NOT by who reposted/quoted.
    """
    tweet_text: str = dspy.InputField(
        desc="Tweet content; may include '@handle wrote: > ...' attribution from quote-tweets"
    )
    author: str = dspy.InputField(
        desc="Display name and @handle of the actual poster (NOT the reposter)"
    )
    is_repost: bool = dspy.InputField()
    is_quote_tweet: bool = dspy.InputField()
    has_media: bool = dspy.InputField(
        desc="True if the tweet has an image, video thumbnail, or link card"
    )
    classification: Literal["news", "info", "banter"] = dspy.OutputField()


class _SummarizeTweet(dspy.Signature):
    """Summarize a tweet for a news-feed reader. Preserve quote-tweet attribution
    and repost authorship verbatim in the summary (e.g. "Andrej Karpathy,
    surfaced via a repost from Sam Altman, ...").

    Output `ItemSummary` fields:
      - key_facts: up to 8 verbatim facts (empty list if there are none)
      - teaser: ≤150 chars hook; for very short posts the teaser MAY be the post itself
      - summary: ≤450 chars; preserve attribution
      - importance: 1=banter/personal, 5=major breaking news
      - category: best fit from the allowed list
    """
    tweet_text: str = dspy.InputField()
    author: str = dspy.InputField()
    context: str = dspy.InputField(
        desc="Structural hints like 'reposted by @sama' or 'quote-tweet of @ylecun'"
    )
    summary: ItemSummary = dspy.OutputField()


class _SummarizeTweetWithImage(dspy.Signature):
    """Summarize a tweet using BOTH its text AND its attached image/media (photo,
    video thumbnail, link-card preview, or quoted-tweet's media). Use the image
    to fill in context the text alone doesn't carry — for media-only posts the
    image IS the news. Preserve attribution. Output schema same as text-only path.
    """
    tweet_text: str = dspy.InputField()
    author: str = dspy.InputField()
    context: str = dspy.InputField()
    image: dspy.Image = dspy.InputField()
    summary: ItemSummary = dspy.OutputField()


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_context(item: dict) -> str:
    rm = item.get("raw_meta") or {}
    parts: list[str] = []
    if rm.get("is_repost"):
        parts.append(
            f"reposted by {rm.get('reposted_by','?')} "
            f"(original poster: {rm.get('author_handle','?')})"
        )
    if rm.get("is_quote_tweet"):
        q = rm.get("quoted_handle") or (
            f"@{rm['quoted_author']}" if rm.get("quoted_author") else "unknown"
        )
        parts.append(f"quote-tweet; quoted account: {q}")
    # `or 1` (not default arg) so an explicit None coerces to 1 instead of
    # raising TypeError on the comparison.
    merged = rm.get("merged_tweet_count") or 1
    if merged > 1:
        parts.append(f"burst-merged from {merged} consecutive tweets")
    return "; ".join(parts) or "standalone tweet"


def _author_label(item: dict) -> str:
    rm = item.get("raw_meta") or {}
    return f"{item.get('author','?')} ({rm.get('author_handle','?')})"


def _image_for_dspy(url: str, *, fetched_at: str | None = None) -> dspy.Image | None:
    """Download an image and return a `dspy.Image` wrapping a base64 data URI.

    Pre-downloading here is required for two reasons:
      1. Ollama (via LiteLLM) does NOT auto-download URL images — passing
         dspy.Image(url) sends the URL string as base64 data, which Ollama
         then fails to decode (`illegal base64 data at input byte 5`, where
         byte 5 is the ':' in 'https:').
      2. Cloud providers (Anthropic, OpenAI) accept data URIs natively, so
         the same code path works for any provider.

    Tight 5s timeout — image fetch sits inside the per-item summarize loop;
    we don't want a slow CDN to stall the whole batch.

    Stale twimg-card skip: card images at pbs.twimg.com/card_img/... expire
    ~24h after the tweet was scraped. If `fetched_at` is older than that,
    skip the network call entirely (would return 404 anyway).

    Returns None on any fetch failure — caller falls back to text-only path.
    """
    if not url:
        return None

    # Skip stale twimg-card URLs without hitting the network.
    if "pbs.twimg.com/card_img" in url and fetched_at:
        try:
            from datetime import datetime, timedelta, timezone
            fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - fetched_dt > timedelta(hours=24):
                log.info("Skipping stale twimg card image (fetched_at=%s): %s",
                         fetched_at, url)
                return None
        except Exception:
            pass  # If parsing fetched_at fails, attempt the fetch.

    try:
        r = httpx.get(
            url,
            timeout=5.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"  # twimg occasionally returns octet-stream
        b64 = base64.b64encode(r.content).decode()
        return dspy.Image(f"data:{ctype};base64,{b64}")
    except Exception as exc:
        log.warning(
            "Image fetch failed (%s) for %s: %s",
            type(exc).__name__, url, exc,
        )
        return None


# ── summarizer ────────────────────────────────────────────────────────────────

class TwitterSummarizer(BaseSummarizer):
    """Classify-then-summarize for Twitter, with optional vision input."""

    def __init__(self) -> None:
        self._classify = dspy.ChainOfThought(_ClassifyTweet)
        self._summarize_text = dspy.ChainOfThought(_SummarizeTweet)
        self._summarize_image = dspy.ChainOfThought(_SummarizeTweetWithImage)

    def _do_classify(self, item: dict) -> str:
        """Returns 'news' | 'info' | 'banter'. Fails open to 'info' on errors —
        we'd rather over-include than silently drop content on a glitch."""
        rm = item.get("raw_meta") or {}
        try:
            pred = predict_with_retry(
                self._classify,
                tweet_text=item.get("content") or "(no caption — media only)",
                author=_author_label(item),
                is_repost=bool(rm.get("is_repost")),
                is_quote_tweet=bool(rm.get("is_quote_tweet")),
                has_media=bool(item.get("image_url")),
            )
            return pred.classification
        except Exception as exc:
            log.warning(
                "Tweet classify failed (%s); defaulting to 'info': %s",
                type(exc).__name__, exc,
            )
            return "info"

    def _do_summary(self, item: dict, *, image: dspy.Image | None) -> SummaryOutcome:
        text = item.get("content") or "(media-only post; no caption)"
        author = _author_label(item)
        context = _build_context(item)
        try:
            if image is not None:
                pred = predict_with_retry(
                    self._summarize_image,
                    tweet_text=text,
                    author=author,
                    context=context,
                    image=image,
                )
            else:
                pred = predict_with_retry(
                    self._summarize_text,
                    tweet_text=text,
                    author=author,
                    context=context,
                )
            return SummaryOutcome.ok(pred.summary)
        except (ValidationError, ValueError) as exc:
            # Bad LM output is transient — retry next run.
            log.warning(
                "TwitterSummarizer parse/validate failed for %r: %s",
                (item.get("title") or item.get("url") or "")[:60], exc,
            )
            return SummaryOutcome.transient()
        except Exception as exc:
            log.warning(
                "TwitterSummarizer failed (%s) for %r: %s",
                type(exc).__name__,
                (item.get("title") or item.get("url") or "")[:60], exc,
            )
            return SummaryOutcome.transient()

    # ── public ────────────────────────────────────────────────────────────────

    def summarize(
        self,
        item: dict,
        *,
        cluster_size: int = 1,
        member_contents: list[str] | None = None,
    ) -> SummaryOutcome:
        # 1. classify — but skip the classifier for reactions.
        # The RelationLinker already certified relation='reaction' by passing
        # cosine ≥ 0.72 against a real news item; that's a high-signal cut.
        # The banter classifier was tuned for standalone tweets where short
        # replies look like noise; applying it to reactions would bury useful
        # context (e.g. "Big if true 🤯" on a real news item).
        if item.get("relation") == "reaction":
            log.debug(
                "reaction → forcing class=info, skipping classifier: %s",
                (item.get("title") or item.get("url") or "")[:80],
            )
            cls = "info"
        else:
            cls = self._do_classify(item)
            if cls == "banter":
                log.info(
                    "Tweet classified 'banter'; permanent skip: %s",
                    (item.get("title") or item.get("url") or "")[:80],
                )
                return SummaryOutcome.skip("banter")

        # 2. summarize, optionally with image
        image_url = (item.get("image_url") or "").strip()
        image = (
            _image_for_dspy(image_url, fetched_at=item.get("fetched_at"))
            if image_url else None
        )
        if image_url and image is None:
            log.info(
                "Image fetch failed; falling back to text-only summary: %s",
                image_url,
            )
        return self._do_summary(item, image=image)
