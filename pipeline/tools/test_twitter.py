"""Smoke test for the Twitter scraper.

Usage:
    python -m pipeline.tools.test_twitter
    python -m pipeline.tools.test_twitter --handles karpathy simonw
    python -m pipeline.tools.test_twitter --save   (writes to snapshot.db)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from pipeline.ingestion.twitter import TwitterPipeline, _load_sources, _env_int

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("test_twitter")


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter scraper smoke test")
    parser.add_argument("--handles", nargs="+", help="Only test these handles")
    parser.add_argument("--days", type=int, default=2, help="Lookback days (default 2)")
    parser.add_argument("--save", action="store_true", help="Persist to snapshot.db")
    parser.add_argument("--db", default=None, help="Custom DB path")
    parser.add_argument("--login", action="store_true", help="Open Chrome for manual X login, then exit")
    args = parser.parse_args()

    if args.login:
        import asyncio
        from playwright.async_api import async_playwright
        from pipeline.ingestion.twitter import _chrome_executable, _chrome_profile_dir, _kill_syndicate_chrome

        async def do_login():
            _kill_syndicate_chrome()
            profile = _chrome_profile_dir()
            exe = _chrome_executable()
            async with async_playwright() as pw:
                launch_kwargs = dict(
                    user_data_dir=profile,
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1280, "height": 900},
                )
                if exe:
                    launch_kwargs["executable_path"] = exe
                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                page = await context.new_page()
                await page.goto("https://x.com/login")
                print("\n  Chrome opened. Log into X now.")
                print("  Waiting 3 minutes for you to complete login...\n")
                for remaining in range(180, 0, -15):
                    print(f"  {remaining}s remaining...", flush=True)
                    await asyncio.sleep(15)
                print("  Time up - saving session.")
                await context.close()
            print("  Session saved. Run the test normally now.\n")

        asyncio.run(do_login())
        return

    # Optionally override sources to just the requested handles
    if args.handles:
        import pipeline.ingestion.twitter as tw_mod
        original_load = tw_mod._load_sources
        handles_set = set(args.handles)
        tw_mod._load_sources = lambda: [
            s for s in original_load() if s["handle"] in handles_set
        ]

    if args.save:
        db_path = args.db or "db/snapshot.db"
        log.info("Saving results to %s", db_path)
        pipeline = TwitterPipeline(db_path=db_path)
    else:
        # dry-run: scrape but don't save - monkey-patch upsert to no-op
        pipeline = TwitterPipeline.__new__(TwitterPipeline)
        pipeline._db_path = None
        pipeline._store = None

        import pipeline.ingestion.twitter as tw_mod
        original_run = tw_mod.TwitterPipeline._run_async

        collected: list[dict] = []

        async def dry_run(self, days):
            import asyncio
            from playwright.async_api import async_playwright
            from pipeline.ingestion.twitter import (
                _chrome_profile_dir, _chrome_executable, _env_bool, _env_int,
                _kill_syndicate_chrome, _load_sources, _scrape_account, TwitterResult,
            )
            sources = _load_sources()
            _kill_syndicate_chrome()
            headless   = _env_bool("TWITTER_HEADLESS", False)
            max_tweets = _env_int("TWITTER_MAX_TWEETS", 15)
            profile    = _chrome_profile_dir()
            exe        = _chrome_executable()
            result = TwitterResult(ok=True)

            launch_kwargs = dict(
                user_data_dir=profile,
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 900},
            )
            if exe:
                launch_kwargs["executable_path"] = exe
            else:
                launch_kwargs["channel"] = "chrome"

            async with async_playwright() as pw:
                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                page = await context.new_page()
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                for source in sources:
                    items = await _scrape_account(page, source, max_tweets, days)
                    collected.extend(items)
                    result.fetched += len(items)
                    import time, random
                    time.sleep(random.uniform(2.0, 4.0))
                await context.close()
            return result, collected

        import asyncio
        result, items = asyncio.run(dry_run(pipeline, args.days))

        print(f"\n{'-'*60}")
        print(f"  Fetched: {result.fetched} tweets (dry run - not saved)")
        print(f"{'-'*60}")
        for item in items:
            print(f"\n@{item['raw_meta']['twitter_handle']}  {item['date']}")
            print(f"  {item['title']}")
            print(f"  {item['url']}")
        print(f"\n{'-'*60}")
        return

    result = pipeline.run(days=args.days)
    print(f"\n{'-'*60}")
    print(f"  fetched={result.fetched}  saved={result.saved}  "
          f"skipped={result.skipped}  failed={result.failed}")
    if result.errors:
        print(f"  errors: {result.errors}")
    print(f"{'-'*60}\n")


if __name__ == "__main__":
    main()
