"""Xquik adapter for Twitter ingestion."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

DEFAULT_BASE_URL = "https://xquik.com/api/v1"
MAX_TWEETS = 200
_METRIC_FIELDS = (
    "bookmarkCount",
    "likeCount",
    "quoteCount",
    "replyCount",
    "retweetCount",
    "viewCount",
)


@dataclass(frozen=True)
class XquikTweet:
    url: str
    text: str
    date: str
    author: str
    author_handle: str
    tweet_id: str
    image_url: str = ""
    metrics: dict[str, int | float] = field(default_factory=dict)


def base_url() -> str:
    raw = (os.getenv("XQUIK_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    return raw if raw.endswith("/api/v1") else f"{raw}/api/v1"


def auth_headers() -> dict[str, str]:
    api_key = (os.getenv("XQUIK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("XQUIK_API_KEY is required when TWITTER_BACKEND=hermes_tweet")
    if api_key.startswith("xq_"):
        return {"X-API-Key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _date(value: Any) -> str:
    raw = _string(value).strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _within_window(date: str, days: int) -> bool:
    if not date:
        return True
    parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
    return parsed >= datetime.now(UTC) - timedelta(days=days)


def _image_url(record: dict[str, Any]) -> str:
    media = record.get("media")
    if not isinstance(media, list):
        return ""
    for item in media:
        if not isinstance(item, dict):
            continue
        image_url = _string(item.get("mediaUrl")).strip()
        parsed = urlparse(image_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return image_url
    return ""


def normalise_tweet(
    record: dict[str, Any],
    source: dict[str, Any],
    *,
    lookback_days: int,
) -> XquikTweet | None:
    if record.get("isReply") is True or record.get("inReplyToId"):
        return None

    tweet_id = _string(record.get("id")).strip()
    source_handle = _string(source["handle"]).lstrip("@")
    if not tweet_id or not source_handle:
        return None

    author_record = record.get("author")
    author = author_record if isinstance(author_record, dict) else {}
    author_handle = _string(author.get("username") or source_handle).lstrip("@")
    url = f"https://x.com/{quote(source_handle, safe='')}/status/{quote(tweet_id, safe='')}"

    date = _date(record.get("createdAt"))
    if not _within_window(date, lookback_days):
        return None

    metrics = {
        key: value
        for key in _METRIC_FIELDS
        if isinstance((value := record.get(key)), (int, float)) and not isinstance(value, bool)
    }
    return XquikTweet(
        url=url,
        text=_string(record.get("text")).strip(),
        date=date,
        author=_string(author.get("name") or source["name"]).strip(),
        author_handle=author_handle,
        tweet_id=tweet_id,
        image_url=_image_url(record),
        metrics=metrics,
    )


async def fetch_account(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    *,
    max_tweets: int,
    lookback_days: int,
) -> list[XquikTweet]:
    handle = _string(source["handle"]).lstrip("@")
    response = await client.get(
        "/x/tweets/search",
        params={
            "q": f"from:{handle}",
            "queryType": "Latest",
            "replies": "exclude",
            "sinceTime": (datetime.now(UTC) - timedelta(days=max(1, lookback_days))).isoformat(),
            "limit": str(max(1, min(max_tweets, MAX_TWEETS))),
        },
    )
    response.raise_for_status()

    payload = response.json()
    records = payload.get("tweets") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise RuntimeError("Xquik response is missing the tweets array")

    tweets = (
        normalise_tweet(record, source, lookback_days=lookback_days)
        for record in records
        if isinstance(record, dict)
    )
    return [tweet for tweet in tweets if tweet is not None]
