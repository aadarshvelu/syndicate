from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

from pipeline import logger as _logger
from pipeline.channel.telegram import TelegramNotifier
from pipeline.git_export import GitExport
from pipeline.main import DigestResult, run
from pipeline.storage import DEFAULT_DB_PATH, now_iso

log = logging.getLogger(__name__)

_INGEST_DAYS = 2
_DEDUP_WINDOW = 10
_SUMMARIZE_LIMIT = 100
_W = 68
_SEP = "═" * _W


@dataclass
class OrchestratorResult:
    started_at: str
    finished_at: str
    ok: bool
    gmail: dict | None = None
    rss: dict | None = None
    twitter: dict | None = None
    embed: dict | None = None
    relation: dict | None = None
    dedup: dict | None = None
    summarize: dict | None = None
    git: dict | None = None
    errors: list[str] = field(default_factory=list)


def _duration(started_at: str, finished_at: str) -> str:
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        s = int((t1 - t0).total_seconds())
        return f"{s // 60}m {s % 60}s"
    except Exception:
        return "?"


def _tick(ok: bool) -> str:
    return "✓" if ok else "✗"


def format_summary(result: OrchestratorResult) -> str:
    """Build the boxed run summary as a single string.

    Shared between stdout (`_print_summary`) and the Telegram notifier so the
    two never drift. Returns the text without a trailing newline.
    """
    dur = _duration(result.started_at, result.finished_at)
    ts = result.finished_at[:19].replace("T", " ") + " UTC"
    status = "OK" if result.ok else "FAILED"

    lines = [
        _SEP,
        f"  SYNDICATE  ·  {ts}  ·  {dur}  ·  {status}",
        _SEP,
    ]

    def row(name: str, d: dict, *parts: str) -> str:
        return f"  {_tick(d.get('ok', True))}  {name:<12}  " + "   ".join(parts)

    if result.gmail:
        g = result.gmail
        lines.append(row("Gmail", g,
            f"fetched={g['fetched']}",
            f"saved={g['saved']}",
            f"skipped={g['skipped']}",
            f"failed={g['failed']}",
        ))

    if result.rss:
        r = result.rss
        lines.append(row("RSS", r,
            f"fetched={r['fetched']}",
            f"saved={r['saved']}",
            f"skipped={r['skipped']}",
            f"failed={r['failed']}",
        ))

    if result.twitter:
        t = result.twitter
        lines.append(row("Twitter", t,
            f"fetched={t['fetched']}",
            f"saved={t['saved']}",
            f"skipped={t['skipped']}",
            f"failed={t['failed']}",
        ))

    if result.embed:
        e = result.embed
        lines.append(row("Embed", e,
            f"examined={e.get('examined', 0)}",
            f"cached={e.get('already_embedded', 0)}",
            f"new={e.get('newly_embedded', 0)}",
            f"failed={e.get('failed', 0)}",
        ))

    if result.relation:
        r = result.relation
        lines.append(row("Relation", r,
            f"examined={r['examined']}",
            f"standalone={r['standalone']}",
            f"reactions={r['reactions']}",
        ))

    if result.dedup:
        d = result.dedup
        methods = "  ".join(f"{k}={v}" for k, v in (d.get("method_counts") or {}).items())
        lines.append(row("Dedup", d,
            f"examined={d['examined']}",
            f"clusters={d['new_clusters']}",
            f"demoted={d['items_demoted']}",
            f"[{methods}]" if methods else "",
        ))

    if result.summarize:
        s = result.summarize
        lines.append(row("Summarize", s,
            f"examined={s['examined']}",
            f"done={s['summarized']}",
            f"skipped={s['skipped']}",
        ))

    if result.git:
        g = result.git
        extras = []
        if g.get("committed"):
            extras.append("committed")
        if g.get("pushed"):
            extras.append("pushed")
        lines.append(row("Git", g,
            f"today=+{g.get('exported_today', 0)}",
            f"yesterday=+{g.get('exported_yesterday', 0)}",
            *extras,
        ))

    lines.append(_SEP)

    if result.errors:
        lines.append("  ERRORS:")
        for e in result.errors:
            lines.append(f"    • {e}")
        lines.append(_SEP)

    return "\n".join(lines)


def _print_summary(result: OrchestratorResult) -> None:
    output = format_summary(result)
    print("\n" + output + "\n")
    log.info("Run summary:\n%s", output)


def _try_export(db_path: str, label: str) -> dict | None:
    """Run GitExport with full exception capture.

    Used twice per orchestrator invocation:
      • pre-flight  — catches anything the previous run summarized but didn't push
      • final       — publishes this run's output (and any orphans the pre-flight missed)

    Returns the asdict-of-result on success, a stub dict on exception, or None
    if nothing to report. Never raises.
    """
    log.info("--- Git export (%s) ---", label)
    try:
        git_result = GitExport(db_path).run()
        d = asdict(git_result)
        if not git_result.ok:
            log.warning("Git export issues (%s): %s", label, git_result.errors)
        else:
            log.info(
                "Git export done (%s): today=%d yesterday=%d committed=%s pushed=%s",
                label, git_result.exported_today, git_result.exported_yesterday,
                git_result.committed, git_result.pushed,
            )
        return d
    except Exception as exc:
        log.exception("Git export crashed (%s)", label)
        return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="syndicate — daily orchestrator (today + yesterday, full pipeline)"
    )
    parser.add_argument("--skip-gmail", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--skip-twitter", action="store_true")
    parser.add_argument("--skip-git", action="store_true", help="Run pipeline but skip git export")
    parser.add_argument("--summarize-limit", type=int, default=_SUMMARIZE_LIMIT,
                        help=f"Max items to summarize per run (default {_SUMMARIZE_LIMIT})")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_path = _logger.setup(verbose=args.verbose)
    started = now_iso()
    pipeline_result: DigestResult | None = None
    git_d: dict | None = None
    interrupt_info: str | None = None

    try:
        db_path = Path(args.db)
        if not db_path.exists():
            log.info("snapshot.db not found — attempting restore from feed repo")
            GitExport(args.db).restore_snapshot(db_path)

        # Pre-flight export. Catches the case where a previous run completed
        # summarize but died before its own export — those rows have summaries
        # in SQLite that never reached news-archive. Publish them now so the
        # PWA stops showing stale data while the laptop hoards finished items.
        if not args.skip_git:
            preflight = _try_export(args.db, "pre-flight catch-up")
            if preflight:
                git_d = preflight
                catch_up = preflight.get("exported_today", 0) + preflight.get("exported_yesterday", 0)
                if catch_up > 0:
                    log.info("Pre-flight published %d orphaned item(s) from prior runs", catch_up)

        log.info("syndicate start — ingest_days=%d dedup_window=%d", _INGEST_DAYS, _DEDUP_WINDOW)

        try:
            pipeline_result = run(
                days=_INGEST_DAYS,
                dedup_window=_DEDUP_WINDOW,
                db_path=args.db,
                skip_gmail=args.skip_gmail,
                skip_rss=args.skip_rss,
                skip_twitter=args.skip_twitter,
                skip_dedup=False,
                skip_summarize=False,
                summarize_limit=args.summarize_limit,
            )
        except KeyboardInterrupt:
            # SIGTERM from the cleaner / launchctl unload, or Ctrl+C from
            # an operator. Don't propagate — fall through to the finally
            # block so the export still runs against whatever's in DB.
            interrupt_info = "KeyboardInterrupt (SIGTERM or Ctrl+C)"
            log.warning("Pipeline interrupted — proceeding to emergency export")

    finally:
        # Final export. Runs unconditionally — even if pipeline crashed or
        # was interrupted mid-stage, anything already in SQLite with a
        # summary gets pushed. This is the resilience guarantee.
        if not args.skip_git:
            final = _try_export(args.db, "final")
            if final:
                git_d = final

        all_errors: list[str] = []
        if pipeline_result is not None:
            all_errors.extend(pipeline_result.errors)
        if interrupt_info:
            all_errors.append(interrupt_info)
        if git_d and not git_d.get("ok"):
            all_errors.extend(git_d.get("errors", []))

        result = OrchestratorResult(
            started_at=started,
            finished_at=now_iso(),
            ok=(not all_errors) and (pipeline_result is not None),
            gmail=getattr(pipeline_result, "gmail", None),
            rss=getattr(pipeline_result, "rss", None),
            twitter=getattr(pipeline_result, "twitter", None),
            embed=getattr(pipeline_result, "embed", None),
            relation=getattr(pipeline_result, "relation", None),
            dedup=getattr(pipeline_result, "dedup", None),
            summarize=getattr(pipeline_result, "summarize", None),
            git=git_d,
            errors=all_errors,
        )

        _print_summary(result)

        # Best-effort Telegram notify. Configured via TELEGRAM_BOT_TOKEN +
        # TELEGRAM_CHAT_ID; silently skips when env not set, and never raises.
        try:
            TelegramNotifier().notify(result)
        except Exception:
            log.exception("Telegram notify crashed (swallowed)")

        _logger.close(log_path)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
