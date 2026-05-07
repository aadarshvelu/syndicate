"""Twitter/X scraper using Playwright with a persistent Chrome profile.

Scrapes recent tweets from configured high-profile accounts and normalises
them into the same item schema used by Gmail/RSS pipelines.

Requirements:
    pip install playwright
    playwright install chrome   (or use system Chrome via channel="chrome")

Env vars (all optional - defaults shown):
    CHROME_PROFILE_DIR   path to Chrome user data dir
    TWITTER_HEADLESS     false
    TWITTER_MAX_TWEETS   15   per account
    TWITTER_LOOKBACK_DAYS 2
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import random
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "twitter_sources.json"

# ── env / defaults ────────────────────────────────────────────────────────────

def _chrome_executable() -> str | None:
    override = os.getenv("CHROME_EXECUTABLE", "").strip()
    if override and Path(override).exists():
        return override
    candidates: list[Path] = []
    if platform.system() == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        candidates = [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium-browser")]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _chrome_profile_dir() -> str:
    override = os.getenv("CHROME_PROFILE_DIR", "").strip()
    if override:
        return override
    # Dedicated separate dir - avoids conflict with your running Chrome instance.
    # Playwright owns this dir exclusively. Log into X once when it first opens.
    if platform.system() == "Windows":
        return str(Path(os.environ["LOCALAPPDATA"]) / "SyndicateBrowser")
    if platform.system() == "Darwin":
        return str(Path.home() / ".syndicate-browser")
    return str(Path.home() / ".syndicate-browser")

def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("1", "true", "yes"):  return True
    if val in ("0", "false", "no"):  return False
    return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TwitterResult:
    ok: bool
    fetched: int = 0
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────

def _dedup_key(tweet_url: str) -> str:
    return hashlib.sha1(tweet_url.encode()).hexdigest()

def _merge_bursts(items: list[dict], gap_min: int = 30) -> list[dict]:
    """Merge consecutive tweets from same account posted within gap_min minutes."""
    if len(items) <= 1:
        return items

    def _dt(item: dict):
        try:
            return datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        except Exception:
            return None

    items = sorted(items, key=lambda x: x["date"])
    merged: list[dict] = []
    group = [items[0]]

    for item in items[1:]:
        prev_dt = _dt(group[-1])
        cur_dt = _dt(item)
        if prev_dt and cur_dt and (cur_dt - prev_dt).total_seconds() <= gap_min * 60:
            group.append(item)
        else:
            merged.append(_collapse_group(group))
            group = [item]
    merged.append(_collapse_group(group))
    return merged

def _collapse_group(group: list[dict]) -> dict:
    if len(group) == 1:
        return group[0]
    urls = sorted(set(g["url"] for g in group))
    combined_text = "\n\n".join(g["content"] for g in group if g["content"])
    base = group[0].copy()
    base["id"] = str(uuid.uuid4())
    base["dedup_key"] = hashlib.sha1("|".join(urls).encode()).hexdigest()
    base["content"] = combined_text
    base["title"] = combined_text[:120].strip().replace("\n", " ") + ("..." if len(combined_text) > 120 else "")
    base["raw_meta"] = {**base.get("raw_meta", {}), "merged_tweet_count": len(group)}
    return base

def _new_id() -> str:
    return str(uuid.uuid4())

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _load_sources() -> list[dict]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return [s for s in json.load(f) if s.get("enabled", True)]

def _kill_syndicate_chrome() -> None:
    _step("Killing any existing SyndicateBrowser Chrome session...")
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-WmiObject Win32_Process -Filter \"Name='chrome.exe'\" | "
                 f"Where-Object {{ $_.CommandLine -like '*SyndicateBrowser*' }} | "
                 f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"],
                capture_output=True, timeout=8,
            )
        else:
            subprocess.run(["pkill", "-f", "SyndicateBrowser"], capture_output=True, timeout=5)
    except Exception as exc:
        _step("Kill step failed (non-fatal): %s", exc)
    time.sleep(1.5)


def _jitter(lo: float = 1.5, hi: float = 4.0) -> None:
    time.sleep(random.uniform(lo, hi))

def _parse_tweet_date(dt_str: str) -> str:
    """Parse ISO datetime string from <time datetime="..."> -> ISO8601 UTC."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return _now_iso()

def _is_within_window(date_iso: str, days: int) -> bool:
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return dt >= cutoff
    except Exception:
        return True

def _tweet_to_item(
    tweet_url: str,
    text: str,
    date_iso: str,
    author: str,
    source: dict,
) -> dict:
    title = text[:120].strip().replace("\n", " ")
    if len(text) > 120:
        title += "..."

    return {
        "id":             _new_id(),
        "dedup_key":      _dedup_key(tweet_url),
        "source_id":      source["id"],
        "source_channel": "twitter",
        "title":          title,
        "desp":           "",
        "date":           date_iso,
        "content":        text,
        "is_html":        0,
        "url":            tweet_url,
        "author":         author,
        "fetched_at":     _now_iso(),
        "image_url":      "",
        "raw_meta": {
            "twitter_handle":   source["handle"],
            "category_hint":    source.get("category_hint", ""),
        },
    }


# ── page interaction ──────────────────────────────────────────────────────────

def _step(msg: str, *args) -> None:
    """Print a visible step to stdout regardless of log level."""
    formatted = msg % args if args else msg
    print(f"  >> {formatted}", flush=True)


async def _check_login_wall(page) -> bool:
    try:
        url = page.url
        if "login" in url or "signup" in url:
            return True
        login_btn = page.locator('[data-testid="loginButton"]')
        return await login_btn.count() > 0
    except Exception:
        return False

async def _click_posts_tab(page) -> None:
    try:
        # Wait up to 8s for the tab to appear
        await page.wait_for_selector('a[role="tab"]', timeout=8000)
        posts_tab = page.locator('a[role="tab"]').filter(has_text=re.compile(r"^Posts$", re.I))
        count = await posts_tab.count()
        if count > 0:
            _step("Clicking 'Posts' tab for chronological order")
            await posts_tab.first.click()
            await asyncio.sleep(2.0)
            _step("Posts tab active")
        else:
            _step("Posts tab not found - continuing with current view")
    except Exception as exc:
        _step("Posts tab click failed: %s", exc)

async def _expand_show_more(page) -> None:
    try:
        show_more = page.locator('[data-testid="tweet-text-show-more-link"]')
        count = await show_more.count()
        if count > 0:
            _step("Expanding %d truncated tweet(s)", count)
            for i in range(min(count, 10)):
                try:
                    await show_more.nth(i).click()
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
    except Exception:
        pass

async def _scrape_account(
    page,
    source: dict,
    max_tweets: int,
    lookback_days: int,
) -> list[dict]:
    handle = source["handle"]
    url = f"https://x.com/{handle}"
    items: list[dict] = []
    seen_urls: set[str] = set()

    print(f"\n{'-'*56}", flush=True)
    print(f"  @{handle}  ({source['name']})", flush=True)
    print(f"{'-'*56}", flush=True)

    try:
        _step("Navigating to %s", url)
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception:
            # networkidle can time out on heavy pages - that's fine, content may still be there
            pass
        _step("Page loaded - current URL: %s", page.url)

        # wait for either tweets or login wall to appear
        try:
            await page.wait_for_selector(
                'article[data-testid="tweet"], [data-testid="loginButton"], input[name="text"]',
                timeout=15000,
            )
        except Exception:
            _step("Timeout waiting for page content - proceeding anyway")
        await asyncio.sleep(1.5)

        if await _check_login_wall(page):
            _step("WARN  Login wall detected - not logged in. Open Chrome manually, log into X, then re-run.")
            log.warning("Twitter: login wall for @%s", handle)
            return []

        _step("Logged in OK")

        await _click_posts_tab(page)
        await asyncio.sleep(1.5)
        await _expand_show_more(page)

        for scroll_n in range(3):
            tweet_articles = page.locator('article[data-testid="tweet"]')
            count = await tweet_articles.count()
            _step("Scroll pass %d - found %d tweet article(s) on page", scroll_n + 1, count)

            for i in range(count):
                if len(items) >= max_tweets:
                    break
                try:
                    article = tweet_articles.nth(i)

                    # skip replies
                    replying = article.locator('div[dir="auto"]').filter(
                        has_text=re.compile(r"Replying to", re.I)
                    )
                    if await replying.count() > 0:
                        log.debug("  skip [%d] reply", i)
                        continue

                    # tweet permalink via <time> parent <a>
                    time_el = article.locator("time").first
                    if await time_el.count() == 0:
                        log.debug("  skip [%d] no <time>", i)
                        continue
                    link_el = time_el.locator("xpath=..")
                    href = await link_el.get_attribute("href")
                    if not href or "/status/" not in href:
                        log.debug("  skip [%d] no status URL", i)
                        continue
                    tweet_url = f"https://x.com{href}" if href.startswith("/") else href

                    if tweet_url in seen_urls:
                        continue
                    seen_urls.add(tweet_url)

                    # date
                    dt_str = await time_el.get_attribute("datetime") or ""
                    date_iso = _parse_tweet_date(dt_str)
                    if not _is_within_window(date_iso, lookback_days):
                        _step("  skip [%d] outside %d-day window (%s)", i, lookback_days, date_iso)
                        continue

                    # text
                    text_el = article.locator('[data-testid="tweetText"]')
                    if await text_el.count() == 0:
                        log.debug("  skip [%d] no tweetText", i)
                        continue
                    text = (await text_el.inner_text()).strip()
                    if text.startswith("RT @"):
                        log.debug("  skip [%d] retweet", i)
                        continue
                    if not text:
                        continue

                    # author
                    name_el = article.locator('[data-testid="User-Name"]')
                    author = source["name"]
                    if await name_el.count() > 0:
                        author = (await name_el.inner_text()).split("\n")[0].strip() or author

                    item = _tweet_to_item(tweet_url, text, date_iso, author, source)
                    items.append(item)
                    _step("OK [%d/%d] %s  %s", len(items), max_tweets, date_iso[:10], tweet_url)

                except Exception as exc:
                    log.debug("  error at tweet[%d]: %s", i, exc)
                    continue

            if len(items) >= max_tweets:
                _step("Reached max_tweets=%d - done", max_tweets)
                break

            _step("Scrolling down for more tweets...")
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(1.5)
            await _expand_show_more(page)

        items = _merge_bursts(items)
        print(f"\n  OK @{handle} -> {len(items)} item(s) after burst merge\n", flush=True)
        return items

    except Exception as exc:
        _step("FAIL Failed scraping @%s: %s", handle, exc)
        log.error("Twitter: failed scraping @%s: %s", handle, exc)
        return []


# ── pipeline class ────────────────────────────────────────────────────────────

class TwitterPipeline:
    def __init__(self, db_path: Path | str | None = None):
        from pipeline.storage import DEFAULT_DB_PATH, ItemStore
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._store = ItemStore(self._db_path)

    def run(self, days: int = 2) -> TwitterResult:
        return asyncio.run(self._run_async(days=days))

    async def _run_async(self, days: int) -> TwitterResult:
        from playwright.async_api import async_playwright

        sources = _load_sources()
        if not sources:
            log.warning("Twitter: no enabled sources in twitter_sources.json")
            return TwitterResult(ok=True)

        headless   = _env_bool("TWITTER_HEADLESS", False)
        max_tweets = _env_int("TWITTER_MAX_TWEETS", 15)
        profile    = _chrome_profile_dir()

        result = TwitterResult(ok=True)

        _step("Twitter pipeline - %d accounts, headless=%s", len(sources), headless)
        _step("Chrome profile: %s", profile)

        try:
            async with async_playwright() as pw:
                exe = _chrome_executable()
                _step("Chrome executable resolved: %s", exe)
                _step("Profile dir: %s", profile)

                if not exe:
                    raise RuntimeError(
                        "Chrome executable not found. Set CHROME_EXECUTABLE env var to your chrome.exe path."
                    )

                _kill_syndicate_chrome()
                _step("Launching Chrome...")
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile,
                    executable_path=exe,
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1280, "height": 900},
                )
                _step("Chrome launched OK")

                page = await context.new_page()
                _step("New tab opened OK")

                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                _step("Stealth script injected OK")

                for source in sources:
                    try:
                        # Recover if the tab was closed between accounts
                        try:
                            await page.title()
                        except Exception:
                            _step("Page closed — opening new tab...")
                            page = await context.new_page()
                            await page.add_init_script(
                                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                            )
                        items = await _scrape_account(page, source, max_tweets, days)
                        result.fetched += len(items)

                        if items:
                            try:
                                saved, skipped = self._store.insert_items(items)
                                result.saved += saved
                                result.skipped += skipped
                            except Exception as exc:
                                result.failed += 1
                                log.warning("Twitter: DB upsert failed: %s", exc)

                    except Exception as exc:
                        result.failed += 1
                        result.errors.append(f"@{source['handle']}: {exc}")
                        log.error("Twitter: account @%s crashed: %s", source["handle"], exc)

                    _jitter(2.0, 5.0)

                _step("Closing browser...")
                await context.close()
                _step("Browser closed OK")

        except Exception as exc:
            result.ok = False
            result.errors.append(f"playwright crash: {exc}")
            log.exception("Twitter: Playwright crashed")

        result.ok = result.ok and result.failed == 0
        log.info(
            "Twitter done: fetched=%d saved=%d skipped=%d failed=%d",
            result.fetched, result.saved, result.skipped, result.failed,
        )
        return result
