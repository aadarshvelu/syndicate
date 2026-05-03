from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from readability import Document
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
}
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
PER_HOST_CONCURRENCY = 3
GLOBAL_CONCURRENCY = 16
MAX_BODY_CHARS = 200_000

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
class FetchResult:
    url: str
    ok: bool
    status: int | None = None
    error: str | None = None
    title: str = ""
    content_html: str = ""
    content_text: str = ""
    image_url: str = ""
    fetch_ms: int = 0


def _extract_og_image(html: str, base_url: str) -> str:
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "lxml")
    for attr, value in [
        ("property", "og:image"),
        ("name",     "twitter:image"),
        ("name",     "twitter:image:src"),
    ]:
        tag = soup.find("meta", attrs={attr: value})
        if tag:
            src = (tag.get("content") or "").strip()
            if src:
                return urljoin(base_url, src)
    return ""


def _extract_body(html: str) -> tuple[str, str, str]:
    try:
        doc = Document(html)
        title = (doc.short_title() or "").strip()
        article_html = doc.summary(html_partial=True)
        text = BeautifulSoup(article_html, "lxml").get_text(" ", strip=True)
        return title, article_html, text[:MAX_BODY_CHARS]
    except Exception as exc:
        log.debug("readability failed, falling back to plain text: %s", exc)
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        return "", "", text[:MAX_BODY_CHARS]


async def _get_host_sem(
    host: str,
    host_sems: dict[str, asyncio.Semaphore],
    host_lock: asyncio.Lock,
) -> asyncio.Semaphore:
    async with host_lock:
        sem = host_sems.get(host)
        if sem is None:
            sem = asyncio.Semaphore(PER_HOST_CONCURRENCY)
            host_sems[host] = sem
        return sem


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    sem_global: asyncio.Semaphore,
    host_sems: dict[str, asyncio.Semaphore],
    host_lock: asyncio.Lock,
) -> FetchResult:
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    sem_host = await _get_host_sem(host, host_sems, host_lock)

    t0 = time.perf_counter()
    async with sem_global, sem_host:
        try:
            resp = await _http_get(client, url)
        except Exception as exc:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return FetchResult(url=url, ok=False, error=f"{type(exc).__name__}: {exc}", fetch_ms=elapsed)
        elapsed = int((time.perf_counter() - t0) * 1000)

        if resp.status_code >= 400:
            return FetchResult(url=url, ok=False, status=resp.status_code, error=f"HTTP {resp.status_code}", fetch_ms=elapsed)

        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "xml" not in ctype:
            return FetchResult(url=url, ok=False, status=resp.status_code, error=f"non-html content-type: {ctype}", fetch_ms=elapsed)

        title, content_html, content_text = _extract_body(resp.text)
        image_url = _extract_og_image(resp.text, url)
        return FetchResult(
            url=url, ok=True, status=resp.status_code,
            title=title, content_html=content_html, content_text=content_text,
            image_url=image_url, fetch_ms=elapsed,
        )


async def fetch_urls(urls: list[str]) -> dict[str, FetchResult]:
    deduped = list(dict.fromkeys(u for u in urls if u))
    if not deduped:
        return {}

    sem_global = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    host_sems: dict[str, asyncio.Semaphore] = {}
    host_lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=BROWSER_HEADERS) as client:
        tasks = [_fetch_one(client, u, sem_global, host_sems, host_lock) for u in deduped]
        results = await asyncio.gather(*tasks)

    return {r.url: r for r in results}
