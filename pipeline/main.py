from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

from pipeline import logger as _logger
from pipeline.AI.summarize import SummarizePipeline
from pipeline.dedup.runner import DedupPipeline
from pipeline.ingestion.gmail import GmailPipeline
from pipeline.ingestion.rss import RssPipeline
from pipeline.ingestion.twitter import TwitterPipeline
from pipeline.relation.linker import RelationLinker
from pipeline.storage import DEFAULT_DB_PATH

log = logging.getLogger(__name__)


@dataclass
class DigestResult:
    started_at: str
    finished_at: str
    ok: bool
    gmail: dict | None = None
    rss: dict | None = None
    twitter: dict | None = None
    relation: dict | None = None
    dedup: dict | None = None
    summarize: dict | None = None
    errors: list[str] = field(default_factory=list)


def run(
    *,
    days: int = 1,
    dedup_window: int = 10,
    db_path: Path | str = DEFAULT_DB_PATH,
    skip_gmail: bool = False,
    skip_rss: bool = False,
    skip_twitter: bool = False,
    skip_dedup: bool = False,
    skip_summarize: bool = False,
    summarize_limit: int = 100,
) -> DigestResult:
    from pipeline.storage import now_iso

    started = now_iso()
    errors: list[str] = []
    gmail_d: dict | None = None
    rss_d: dict | None = None
    twitter_d: dict | None = None
    relation_d: dict | None = None
    dedup_d: dict | None = None

    if not skip_gmail:
        log.info("--- Gmail ingestion ---")
        try:
            result = GmailPipeline(db_path=db_path).run(days=days)
            gmail_d = asdict(result)
            if not result.ok:
                errors.append(f"gmail: {result.errors}")
            log.info(
                "Gmail done: fetched=%d saved=%d skipped=%d failed=%d",
                result.fetched, result.saved, result.skipped, result.failed,
            )
        except Exception as exc:
            errors.append(f"gmail crash: {type(exc).__name__}: {exc}")
            log.exception("Gmail pipeline crashed")

    if not skip_rss:
        log.info("--- RSS ingestion ---")
        try:
            result = RssPipeline(db_path=db_path).run(days=days)
            rss_d = asdict(result)
            if not result.ok:
                errors.append(f"rss: {result.errors}")
            log.info(
                "RSS done: fetched=%d saved=%d skipped=%d failed=%d",
                result.fetched, result.saved, result.skipped, result.failed,
            )
        except Exception as exc:
            errors.append(f"rss crash: {type(exc).__name__}: {exc}")
            log.exception("RSS pipeline crashed")

    if not skip_twitter:
        log.info("--- Twitter ingestion ---")
        try:
            result = TwitterPipeline(db_path=db_path).run(days=days)
            twitter_d = asdict(result)
            if not result.ok:
                errors.append(f"twitter: {result.errors}")
            log.info(
                "Twitter done: fetched=%d saved=%d skipped=%d failed=%d",
                result.fetched, result.saved, result.skipped, result.failed,
            )
        except Exception as exc:
            errors.append(f"twitter crash: {type(exc).__name__}: {exc}")
            log.exception("Twitter pipeline crashed")

    log.info("--- Relation linking ---")
    try:
        result = RelationLinker(db_path=db_path).run()
        relation_d = asdict(result)
        if not result.ok:
            errors.append(f"relation: {result.errors}")
        log.info(
            "Relation done: examined=%d standalone=%d reactions=%d",
            result.examined, result.standalone, result.reactions,
        )
    except Exception as exc:
        errors.append(f"relation crash: {type(exc).__name__}: {exc}")
        log.exception("Relation linker crashed")

    if not skip_dedup:
        log.info("--- Dedup (T1-T4) ---")
        try:
            result = DedupPipeline(db_path=db_path).run(window_days=dedup_window)
            dedup_d = asdict(result)
            if not result.ok:
                errors.append(f"dedup: {result.errors}")
            log.info(
                "Dedup done: examined=%d new_clusters=%d demoted=%d p1=%d p2=%d methods=%s",
                result.examined, result.new_clusters, result.items_demoted,
                result.matched_phase1, result.matched_phase2,
                result.method_counts,
            )
        except Exception as exc:
            errors.append(f"dedup crash: {type(exc).__name__}: {exc}")
            log.exception("Dedup pipeline crashed")

    summarize_d: dict | None = None
    if not skip_summarize:
        log.info("--- Summarize ---")
        try:
            result = SummarizePipeline(db_path=db_path).run(limit=summarize_limit)
            summarize_d = asdict(result)
            if not result.ok:
                errors.append(f"summarize: {result.errors}")
            log.info(
                "Summarize done: examined=%d summarized=%d skipped=%d",
                result.examined, result.summarized, result.skipped,
            )
        except Exception as exc:
            errors.append(f"summarize crash: {type(exc).__name__}: {exc}")
            log.exception("Summarize pipeline crashed")

    finished = now_iso()
    return DigestResult(
        started_at=started,
        finished_at=finished,
        ok=not errors,
        gmail=gmail_d,
        rss=rss_d,
        twitter=twitter_d,
        relation=relation_d,
        dedup=dedup_d,
        summarize=summarize_d,
        errors=errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="syndicate digest — full ingestion + dedup")
    parser.add_argument("--days", type=int, default=1, help="Ingestion lookback in days (default 1)")
    parser.add_argument("--window", type=int, default=10, help="Dedup cluster window in days (default 10)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument("--skip-gmail", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--skip-twitter", action="store_true")
    parser.add_argument("--skip-dedup", action="store_true")
    parser.add_argument("--skip-summarize", action="store_true")
    parser.add_argument("--summarize-limit", type=int, default=100, help="Max items to summarize per run (default 100)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_path = _logger.setup(verbose=args.verbose)
    try:
        result = run(
            days=args.days,
            dedup_window=args.window,
            db_path=args.db,
            skip_gmail=args.skip_gmail,
            skip_rss=args.skip_rss,
            skip_twitter=args.skip_twitter,
            skip_dedup=args.skip_dedup,
            skip_summarize=args.skip_summarize,
            summarize_limit=args.summarize_limit,
        )
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1
    finally:
        _logger.close(log_path)


if __name__ == "__main__":
    sys.exit(main())
