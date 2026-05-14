"""Manual-validation runner for the Twitter scraper.

Scrapes a small number of handles, prints each tweet in a human-readable
format so you can eyeball whether the data looks right (especially
quote-tweet handling), and mirrors every step/wait/loop to both the
terminal and a timestamped log file under __test__/logs/.

Usage:
    uv run python -m __test__.validate_twitter
    uv run python -m __test__.validate_twitter --handles AnthropicAI emollick --days 2
    uv run python -m __test__.validate_twitter --max 5

The scraper's own _step() prints (Navigating to..., Scroll pass N..., etc.)
are forwarded to the log file via a stdout tee, so the file ends up with
the full action trace plus our timestamped wrapper messages.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

from pipeline.ingestion.twitter import (  # noqa: E402
    _chrome_executable,
    _chrome_profile_dir,
    _env_bool,
    _env_int,
    _kill_syndicate_chrome,
    _load_sources,
    _scrape_account,
)


class _Tee:
    """Forward writes to multiple streams. Lets us mirror raw print()
    output (used by twitter._step) into our log file."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


def _setup_logging(log_path: Path) -> tuple[logging.Logger, object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8", buffering=1)

    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    for noisy in ("playwright", "asyncio", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    log = logging.getLogger("validate_twitter")
    log.info("Log file: %s", log_path)
    return log, log_file


def _format_tweet(idx: int, total: int, item: dict) -> str:
    rm = item["raw_meta"]
    handle = rm.get("twitter_handle", "?")
    author_handle = rm.get("author_handle", "")
    quoted_handle = rm.get("quoted_handle", "")
    quoted_author = rm.get("quoted_author", "")
    is_quote = rm.get("is_quote_tweet", False)
    is_repost = rm.get("is_repost", False)
    reposted_by = rm.get("reposted_by", "")
    merged = rm.get("merged_tweet_count", 1)

    type_tags = []
    if is_repost:
        type_tags.append(f"REPOST (reposted by {reposted_by or '?'})")
    if is_quote:
        label = quoted_handle or (f"@{quoted_author}" if quoted_author else "?")
        type_tags.append(f"QUOTE-TWEET (quoted: {label})")
    if merged > 1:
        type_tags.append(f"BURST-MERGED ({merged} tweets)")
    type_str = ", ".join(type_tags) if type_tags else "standalone"

    author_line = f"{item['author']}"
    if author_handle:
        author_line += f"  ({author_handle})"

    bar = "━" * 72
    lines = [
        bar,
        f"  TWEET {idx}/{total}  from feed @{handle}",
        f"  Date    : {item['date']}",
        f"  Author  : {author_line}",
        f"  URL     : {item['url']}",
        f"  Type    : {type_str}",
    ]
    if is_quote:
        lines.append(f"  Quoted  : handle={quoted_handle or '(none)'}  display={quoted_author or '(none)'}")
    lines.append(f"  Image   : {item.get('image_url') or '(none)'}")
    lines.append(f"  Title   : {item['title']}")
    lines.append("  " + ("-" * 70))
    lines.append("  CONTENT:")
    for line in item["content"].splitlines() or [""]:
        lines.append(f"    {line}")
    lines.append("")
    return "\n".join(lines)


async def _scrape_handles(
    handles: list[str] | None,
    days: int,
    max_tweets: int,
    log: logging.Logger,
) -> list[dict]:
    from playwright.async_api import async_playwright

    sources = _load_sources()
    if handles:
        wanted = set(handles)
        sources = [s for s in sources if s["handle"] in wanted]
    if not sources:
        log.error("No matching sources. Requested: %s", handles)
        return []

    log.info("=" * 72)
    log.info("Plan: %d handle(s)  days=%d  max_tweets=%d", len(sources), days, max_tweets)
    for s in sources:
        log.info("  - @%s  (%s)", s["handle"], s.get("name", ""))
    log.info("=" * 72)

    headless = _env_bool("TWITTER_HEADLESS", False)
    profile = _chrome_profile_dir()
    exe = _chrome_executable()

    log.info("Chrome profile  : %s", profile)
    log.info("Chrome binary   : %s", exe)
    log.info("Headless mode   : %s", headless)

    log.info("Killing any existing SyndicateBrowser Chrome session...")
    _kill_syndicate_chrome()

    all_items: list[dict] = []
    async with async_playwright() as pw:
        kwargs = dict(
            user_data_dir=profile,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900},
        )
        if exe:
            kwargs["executable_path"] = exe

        log.info("Launching Chrome...")
        t0 = time.monotonic()
        context = await pw.chromium.launch_persistent_context(**kwargs)
        log.info("Chrome launched in %.1fs", time.monotonic() - t0)

        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        log.info("Stealth init script injected")

        for idx, source in enumerate(sources, 1):
            log.info("")
            log.info(">>> [%d/%d] Scraping @%s ...", idx, len(sources), source["handle"])
            t_acc = time.monotonic()
            try:
                items = await asyncio.wait_for(
                    _scrape_account(page, source, max_tweets, days),
                    timeout=360,
                )
                elapsed = time.monotonic() - t_acc
                log.info(
                    "<<< [%d/%d] @%s done in %.1fs -> %d item(s)",
                    idx, len(sources), source["handle"], elapsed, len(items),
                )
                all_items.extend(items)
            except asyncio.TimeoutError:
                log.error(
                    "<<< [%d/%d] @%s TIMED OUT after %.1fs",
                    idx, len(sources), source["handle"], time.monotonic() - t_acc,
                )
            except Exception:
                log.exception(
                    "<<< [%d/%d] @%s crashed",
                    idx, len(sources), source["handle"],
                )

        log.info("")
        log.info("Closing Chrome...")
        await context.close()
        log.info("Chrome closed")

    return all_items


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--handles", nargs="+",
        default=["AnthropicAI", "emollick"],
        help="Handles to scrape (default: AnthropicAI emollick)",
    )
    p.add_argument("--days", type=int, default=2, help="Lookback days (default 2)")
    p.add_argument(
        "--max", type=int, dest="max_tweets",
        default=_env_int("TWITTER_MAX_TWEETS", 15),
        help="Max tweets per handle",
    )
    p.add_argument(
        "--log-dir", default=str(_ROOT / "__test__" / "logs"),
        help="Where to write the log file",
    )
    args = p.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(args.log_dir) / f"twitter_validate_{ts}.log"
    log, log_file = _setup_logging(log_path)

    log.info("validate_twitter starting at %s", datetime.now().isoformat(timespec="seconds"))
    log.info("Args: handles=%s days=%d max=%d", args.handles, args.days, args.max_tweets)

    t_start = time.monotonic()
    try:
        items = asyncio.run(
            _scrape_handles(args.handles, args.days, args.max_tweets, log)
        )
    finally:
        elapsed = time.monotonic() - t_start

    log.info("=" * 72)
    log.info("Scrape complete in %.1fs - %d total item(s)", elapsed, len(items))
    log.info("=" * 72)
    log.info("")
    log.info("Below: each tweet for manual validation. Inspect:")
    log.info("  * Author and date are non-empty and plausible")
    log.info("  * URL points to /status/")
    log.info("  * Title is the first ~120 chars of CONTENT")
    log.info("  * For QUOTE-TWEETs, the '@X wrote:' attribution + quoted text is present")
    log.info("  * For BURST-MERGED, content is multi-paragraph")
    log.info("")

    for i, item in enumerate(items, 1):
        print(_format_tweet(i, len(items), item))

    log.info("=" * 72)
    log.info("Validation output ends. Full log written to %s", log_path)
    log_file.close()


if __name__ == "__main__":
    main()
