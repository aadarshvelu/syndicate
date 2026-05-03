from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipeline.ingestion import sources as sources_mod
from pipeline.auth.gmail import session
from pipeline.ingestion.extract_email import extract
from pipeline.extractors import dispatch
from pipeline.ingestion.normalize import gmail_to_item
from pipeline.ingestion.imap import (
    extract_html_payload,
    fetch_message,
    get_header,
    search_uids,
    select_label,
)
from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)


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


class GmailPipeline:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def collect(self, *, days: int = 1, folder: str = "INBOX") -> list[dict]:
        sources = sources_mod.load()
        items: list[dict] = []
        try:
            with session() as imap:
                select_label(imap, folder, readonly=True)
                uids = search_uids(imap, lookback_days=days)
                log.info("Gmail collect: %d UIDs (folder=%s, days=%d)", len(uids), folder, days)
                for uid in uids:
                    try:
                        msg, gmail_meta = fetch_message(imap, uid)
                        from_h = get_header(msg, "From")
                        subject = get_header(msg, "Subject")
                        date_h = get_header(msg, "Date")
                        source_id, _extractor = dispatch(from_h, sources)
                        html, text = extract_html_payload(msg)
                        extracted = extract(html, text, subject, from_h, date_h)
                        if not extracted.title and not extracted.text:
                            log.debug("empty payload uid=%s", uid.decode())
                            continue
                        raw_meta = {
                            "gmail_uid": uid.decode(),
                            "gmail_labels": gmail_meta.get("labels", []),
                            "gmail_msgid": gmail_meta.get("msgid"),
                            "gmail_thrid": gmail_meta.get("thrid"),
                        }
                        items.append(gmail_to_item(extracted, source_id, uid.decode(), raw_meta))
                    except Exception:
                        log.exception("gmail collect: failed uid=%r", uid)
        except Exception:
            log.exception("Gmail collect: session failed")
        return items

    def run(
        self,
        *,
        days: int = 1,
        folder: str = "INBOX",
        dump_json: Path | str | None = None,
    ) -> PipelineResult:
        started = now_iso()
        sources = sources_mod.load()
        items: list[dict] = []
        errors: list[str] = []
        failed = 0

        try:
            with session() as imap:
                select_label(imap, folder, readonly=True)
                uids = search_uids(imap, lookback_days=days)
                log.info("Gmail: %d UIDs in window (folder=%s, days=%d)", len(uids), folder, days)

                for uid in uids:
                    try:
                        msg, gmail_meta = fetch_message(imap, uid)
                        from_h = get_header(msg, "From")
                        subject = get_header(msg, "Subject")
                        date_h = get_header(msg, "Date")
                        source_id, _extractor = dispatch(from_h, sources)
                        html, text = extract_html_payload(msg)
                        extracted = extract(html, text, subject, from_h, date_h)
                        if not extracted.title and not extracted.text:
                            failed += 1
                            errors.append(f"empty payload uid={uid.decode()}")
                            continue
                        raw_meta = {
                            "gmail_uid": uid.decode(),
                            "gmail_labels": gmail_meta.get("labels", []),
                            "gmail_msgid": gmail_meta.get("msgid"),
                            "gmail_thrid": gmail_meta.get("thrid"),
                        }
                        item = gmail_to_item(extracted, source_id, uid.decode(), raw_meta)
                        items.append(item)
                    except Exception as exc:
                        failed += 1
                        errors.append(f"uid={uid.decode()}: {type(exc).__name__}: {exc}")
                        log.exception("Failed processing UID %r", uid)
        except Exception as exc:
            errors.append(f"session: {type(exc).__name__}: {exc}")
            log.exception("Gmail session failed")

        if dump_json:
            _dump_items(items, dump_json, channel="gmail", started_at=started)

        with ItemStore(self.db_path) as store:
            run_id = store.start_run("gmail")
            saved, skipped = store.insert_items(items)
            ok = (not errors) and failed == 0
            store.finish_run(
                run_id, ok=ok, fetched=len(items) + failed,
                saved=saved, skipped=skipped, failed=failed, errors=errors,
            )

        finished = now_iso()
        return PipelineResult(
            channel="gmail", started_at=started, finished_at=finished,
            fetched=len(items) + failed, saved=saved, skipped=skipped,
            failed=failed, ok=ok, errors=errors, run_id=run_id,
        )


def _dump_items(items: list[dict], path: Path | str, *, channel: str, started_at: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"channel": channel, "started_at": started_at, "count": len(items), "items": items}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Dumped %d items to %s", len(items), path)


def _print_result(result: PipelineResult) -> None:
    payload = asdict(result)
    if len(payload.get("errors") or []) > 10:
        payload["errors"] = payload["errors"][:10] + [f"... ({len(result.errors) - 10} more truncated)"]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Gmail ingestion pipeline")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--folder", default="INBOX")
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

    pipeline = GmailPipeline(db_path=args.db)
    result = pipeline.run(days=args.days, folder=args.folder, dump_json=args.dump_json)
    _print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
