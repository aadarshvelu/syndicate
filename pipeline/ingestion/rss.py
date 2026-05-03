from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipeline.ingestion.fetch import fetch_urls
from pipeline.ingestion.normalize import rss_to_item
from pipeline.ingestion.feeds import fetch_all, window_since
from pipeline.storage import (
    DEFAULT_DB_PATH,
    ItemStore,
    dedup_key_for_msg,
    dedup_key_for_url,
    now_iso,
)

log = logging.getLogger(__name__)

RSS_CONFIG_PATH = Path("config") / "rss_sources.json"


@dataclass
class PipelineResult:
    channel: str
    started_at: str
    finished_at: str
    fetched: int
    saved: int
    skipped: int
    failed: int
    ok: bool
    errors: list[str] = field(default_factory=list)
    run_id: int = 0


def _load_sources() -> list[dict]:
    if not RSS_CONFIG_PATH.exists():
        raise FileNotFoundError(f"RSS source registry missing at {RSS_CONFIG_PATH}")
    return json.loads(RSS_CONFIG_PATH.read_text(encoding="utf-8")).get("sources", [])


def _entry_dedup_key(entry: dict, source: dict) -> str:
    url = entry.get("link") or ""
    if url:
        return dedup_key_for_url(url)
    return dedup_key_for_msg(source.get("id", ""), entry.get("title") or "")


def _dump_items(items: list[dict], path: Path | str, *, channel: str, started_at: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"channel": channel, "started_at": started_at, "count": len(items), "items": items}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Dumped %d items to %s", len(items), path)


class RssPipeline:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def collect(self, *, days: int = 1, do_fetch: bool = True) -> list[dict]:
        return asyncio.run(self._collect_async(days=days, do_fetch=do_fetch))

    async def _collect_async(self, *, days: int, do_fetch: bool) -> list[dict]:
        sources = _load_sources()
        src_by_id = {s["id"]: s for s in sources}
        since = window_since(days)
        feed_results = await fetch_all(sources, since=since)

        candidates: list[tuple[dict, dict, str]] = []
        for fr in feed_results:
            if not fr.ok:
                log.warning("RSS collect: feed %s failed: %s", fr.source_id, fr.error)
                continue
            src = src_by_id.get(fr.source_id, {})
            for entry in fr.entries:
                dk = _entry_dedup_key(entry, src)
                candidates.append((entry, src, dk))

        url_targets: list[str] = []
        if do_fetch:
            for entry, src, _dk in candidates:
                if not src.get("fetch_full"):
                    continue
                link = entry.get("link") or ""
                if link:
                    url_targets.append(link)
        fetched_articles = await fetch_urls(url_targets) if url_targets else {}

        items: list[dict] = []
        for entry, src, _dk in candidates:
            try:
                link = entry.get("link") or ""
                fr_url = fetched_articles.get(link) if (do_fetch and src.get("fetch_full")) else None
                item = rss_to_item(entry, fr_url, src)
                if item is None:
                    continue
                items.append(item)
            except Exception:
                log.exception("RSS collect: failed entry from %s", src.get("id"))

        log.info("RSS collect: %d items from %d candidates", len(items), len(candidates))
        return items

    def run(
        self,
        *,
        days: int = 1,
        do_fetch: bool = True,
        dump_json: Path | str | None = None,
    ) -> PipelineResult:
        return asyncio.run(self._run_async(days=days, do_fetch=do_fetch, dump_json=dump_json))

    async def _run_async(
        self,
        *,
        days: int,
        do_fetch: bool,
        dump_json: Path | str | None,
    ) -> PipelineResult:
        started = now_iso()
        sources = _load_sources()
        src_by_id = {s["id"]: s for s in sources}
        since = window_since(days)
        errors: list[str] = []
        failed = 0
        pre_skipped = 0

        feed_results = await fetch_all(sources, since=since)

        candidates: list[tuple[dict, dict, str]] = []
        for fr in feed_results:
            if not fr.ok:
                failed += 1
                errors.append(f"feed {fr.source_id}: {fr.error}")
                continue
            src = src_by_id.get(fr.source_id, {})
            for entry in fr.entries:
                dk = _entry_dedup_key(entry, src)
                candidates.append((entry, src, dk))

        with ItemStore(self.db_path) as store:
            existing = store.existing_dedup_keys([dk for (_, _, dk) in candidates])
        fresh = [(e, s, dk) for (e, s, dk) in candidates if dk not in existing]
        pre_skipped = len(candidates) - len(fresh)
        log.info(
            "RSS: %d entries pulled, %d already in DB (skip), %d fresh",
            len(candidates), pre_skipped, len(fresh),
        )

        url_targets: list[str] = []
        if do_fetch:
            for entry, src, _dk in fresh:
                if not src.get("fetch_full"):
                    continue
                link = entry.get("link") or ""
                if link:
                    url_targets.append(link)
        fetched_articles = await fetch_urls(url_targets) if url_targets else {}

        items: list[dict] = []
        for entry, src, _dk in fresh:
            try:
                link = entry.get("link") or ""
                fr_url = (
                    fetched_articles.get(link)
                    if (do_fetch and src.get("fetch_full"))
                    else None
                )
                item = rss_to_item(entry, fr_url, src)
                if item is None:
                    failed += 1
                    continue
                items.append(item)
            except Exception as exc:
                failed += 1
                errors.append(f"entry {src.get('id')}/{entry.get('id', '?')}: {type(exc).__name__}: {exc}")
                log.exception("Failed processing entry from %s", src.get("id"))

        if dump_json:
            _dump_items(items, dump_json, channel="rss", started_at=started)

        with ItemStore(self.db_path) as store:
            run_id = store.start_run("rss")
            saved, db_skipped = store.insert_items(items)
            skipped = pre_skipped + db_skipped
            ok = (not errors) and failed == 0
            store.finish_run(
                run_id, ok=ok, fetched=len(candidates),
                saved=saved, skipped=skipped, failed=failed, errors=errors,
            )

        finished = now_iso()
        return PipelineResult(
            channel="rss", started_at=started, finished_at=finished,
            fetched=len(candidates), saved=saved, skipped=skipped,
            failed=failed, ok=ok, errors=errors, run_id=run_id,
        )


def _print_result(result: PipelineResult) -> None:
    payload = asdict(result)
    if len(payload.get("errors") or []) > 10:
        payload["errors"] = payload["errors"][:10] + [f"... ({len(result.errors) - 10} more truncated)"]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="RSS ingestion pipeline")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--dump-json", default=None)
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

    pipeline = RssPipeline(db_path=args.db)
    result = pipeline.run(days=args.days, do_fetch=not args.no_fetch, dump_json=args.dump_json)
    _print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
