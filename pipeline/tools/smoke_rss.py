from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from pipeline.ingestion.fetch import FetchResult, fetch_urls
from pipeline.ingestion.feeds import fetch_all, window_since

CONFIG_PATH = Path("config") / "rss_sources.json"


def load_sources() -> list[dict]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"RSS source registry missing at {CONFIG_PATH}")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("sources", [])


def collect_fetch_targets(sources: list[dict], feed_results, limit: int) -> list[str]:
    src_by_id = {s["id"]: s for s in sources}
    urls: list[str] = []
    for r in feed_results:
        if not r.ok:
            continue
        src = src_by_id.get(r.source_id, {})
        if not src.get("fetch_full"):
            continue
        for entry in r.entries[:limit]:
            link = entry.get("link") or ""
            if link:
                urls.append(link)
    return urls


async def run(limit: int, do_fetch: bool, days: int) -> int:
    sources = load_sources()
    since = window_since(days)
    print(
        f"[fetching {len(sources)} feeds in parallel; window: entries since "
        f"{since.isoformat()} ({days} day{'s' if days > 1 else ''})]\n",
        file=sys.stderr,
    )

    feed_results = await fetch_all(sources, since=since)

    fetched: dict[str, FetchResult] = {}
    if do_fetch:
        targets = collect_fetch_targets(sources, feed_results, limit)
        print(f"[fetching {len(targets)} article URLs in parallel]\n", file=sys.stderr)
        fetched = await fetch_urls(targets)

    src_by_id = {s["id"]: s for s in sources}
    ok = failed = total_entries = 0
    fetch_ok = fetch_fail = 0

    for r in feed_results:
        bar = "=" * 80
        print(bar)
        if not r.ok:
            failed += 1
            print(f"[FAIL] {r.source_id} ({r.fetch_ms}ms) :: {r.error}")
            print(f"       URL: {r.url}")
            print()
            continue

        ok += 1
        total_entries += len(r.entries)
        bozo_tag = " [bozo]" if r.bozo else ""
        src = src_by_id.get(r.source_id, {})
        fetch_tag = " [fetch_full]" if src.get("fetch_full") else ""
        print(f"[OK]   {r.source_id} ({r.fetch_ms}ms){bozo_tag}{fetch_tag} :: {len(r.entries)} entries")
        print(f"       Feed: {r.feed_title}")
        print(f"       URL:  {r.url}")
        if r.bozo:
            print(f"       Bozo: {r.bozo_reason}")
        print()

        for entry in r.entries[:limit]:
            print(f"  - {entry['title'] or '(no title)'}")
            if entry["author"]:
                print(f"    by {entry['author']}")
            print(f"    {entry['link']}")
            print(f"    {entry['published']}")
            if entry["tags"]:
                print(f"    tags: {', '.join(entry['tags'])}")

            link = entry.get("link") or ""
            fr = fetched.get(link) if do_fetch and src.get("fetch_full") else None
            teaser = (entry["summary"] or "").replace("\n", " ").strip()

            if fr and fr.ok:
                fetch_ok += 1
                text = fr.content_text or ""
                print(f"    [body ({fr.fetch_ms}ms)] {len(text)} chars, title='{fr.title or '(none)'}'")
                preview = text[:280].replace("\n", " ").strip()
                if preview:
                    ellipsis = "..." if len(text) > 280 else ""
                    print(f"    {preview}{ellipsis}")
            elif fr and not fr.ok:
                fetch_fail += 1
                print(f"    [body FAIL: {fr.error}; falling back to teaser]")
                if teaser:
                    preview = teaser[:240]
                    ellipsis = "..." if len(teaser) > 240 else ""
                    print(f"    [teaser] {preview}{ellipsis}")
            else:
                if teaser:
                    preview = teaser[:240]
                    ellipsis = "..." if len(teaser) > 240 else ""
                    print(f"    [teaser] {preview}{ellipsis}")
            print()

    print("=" * 80, file=sys.stderr)
    print(f"[feeds] {ok}/{len(feed_results)} OK, {failed} failed, {total_entries} total entries", file=sys.stderr)
    if do_fetch:
        print(f"[urls]  {fetch_ok} fetched, {fetch_fail} failed", file=sys.stderr)
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="RSS smoke test")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(run(args.limit, do_fetch=not args.no_fetch, days=args.days))


if __name__ == "__main__":
    sys.exit(main())
