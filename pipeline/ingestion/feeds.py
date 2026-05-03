from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = "syndicate-news-digest/0.1 (+personal pipeline)"
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
    "application/json;q=0.8, text/xml;q=0.7, */*;q=0.5"
)

NETWORK_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.NetworkError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(NETWORK_ERRORS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
async def _http_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    return await client.get(url, follow_redirects=True)


@dataclass
class FeedResult:
    source_id: str
    url: str
    ok: bool
    status: int | None = None
    error: str | None = None
    feed_title: str = ""
    entries: list[dict] = field(default_factory=list)
    fetch_ms: int = 0
    bozo: bool = False
    bozo_reason: str = ""


def _parse_entry_date(e: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = e.get(key)
        if not st:
            continue
        try:
            return datetime(*st[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _entry_to_dict(e: dict) -> dict:
    dt = _parse_entry_date(e)
    return {
        "title": (e.get("title") or "").strip(),
        "link": e.get("link") or "",
        "summary": e.get("summary") or e.get("description") or "",
        "published": e.get("published") or e.get("updated") or "",
        "published_at": dt,
        "author": e.get("author") or "",
        "id": e.get("id") or e.get("link") or e.get("title") or "",
        "tags": [t.get("term", "") for t in (e.get("tags") or []) if t.get("term")],
    }


async def fetch_one(
    client: httpx.AsyncClient,
    source: dict,
    since: datetime | None = None,
    drop_undated: bool = True,
) -> FeedResult:
    url = source["url"]
    sid = source["id"]
    t0 = time.perf_counter()
    try:
        resp = await _http_get(client, url)
        elapsed = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            return FeedResult(
                source_id=sid, url=url, ok=False,
                status=resp.status_code, error=f"HTTP {resp.status_code}", fetch_ms=elapsed,
            )
        parsed = feedparser.parse(resp.content)
        feed_title = ""
        if hasattr(parsed, "feed"):
            feed_title = parsed.feed.get("title", "") or ""
        all_entries = [_entry_to_dict(e) for e in (parsed.entries or [])]
        if since is not None:
            entries = []
            for ent in all_entries:
                dt = ent.get("published_at")
                if dt is None:
                    if not drop_undated:
                        entries.append(ent)
                    continue
                if dt >= since:
                    entries.append(ent)
        else:
            entries = all_entries
        bozo = bool(getattr(parsed, "bozo", False))
        bozo_reason = ""
        if bozo:
            exc = getattr(parsed, "bozo_exception", None)
            bozo_reason = repr(exc) if exc else "unknown parse warning"
        return FeedResult(
            source_id=sid, url=url, ok=True, status=resp.status_code,
            feed_title=feed_title, entries=entries, fetch_ms=elapsed,
            bozo=bozo, bozo_reason=bozo_reason,
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        return FeedResult(
            source_id=sid, url=url, ok=False,
            error=f"{type(exc).__name__}: {exc}", fetch_ms=elapsed,
        )


async def fetch_all(
    sources: list[dict],
    since: datetime | None = None,
    drop_undated: bool = True,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> list[FeedResult]:
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        return await asyncio.gather(
            *(fetch_one(client, s, since=since, drop_undated=drop_undated) for s in sources)
        )


def window_since(days: int) -> datetime:
    if days < 1:
        days = 1
    today_midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return today_midnight - timedelta(days=days - 1)
