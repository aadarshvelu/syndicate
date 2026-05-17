"""Unified CLI dispatcher for every pipeline stage.

Each subcommand emits a single JSON object on stdout:
    {"ok": bool, "result": <stage-specific dict>, "log_path": "logs/<date>.txt"}

Used by the Claude Code Agent Skills under skills/ — each SKILL.md runs
`uv run python -m pipeline.cli <subcommand> --json [flags]` and parses the
result.

Mirrors the orchestrator's boot sequence (load .env -> setup logger -> run
-> close logger), but per-stage rather than the full pipeline so an agent
can drive stages independently. The existing `uv run syndicate` entry point
keeps working unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

# Imports below this line are safe — load_dotenv has populated os.environ
# so AI provider keys, OLLAMA_HOST overrides, etc. resolve correctly.
from pipeline import logger as _logger  # noqa: E402
from pipeline.storage import DEFAULT_DB_PATH  # noqa: E402

log = logging.getLogger(__name__)


def _emit(payload: dict[str, Any]) -> None:
    """Write the JSON envelope to stdout, flushed."""
    json.dump(payload, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _result_dict(result: Any) -> dict[str, Any]:
    if is_dataclass(result) and not isinstance(result, type):
        d = asdict(result)
    elif isinstance(result, dict):
        d = result
    else:
        d = {"value": str(result)}
    # Truncate runaway error lists so the JSON stays scannable.
    errs = d.get("errors")
    if isinstance(errs, list) and len(errs) > 10:
        d["errors"] = errs[:10] + [f"... ({len(errs) - 10} more truncated)"]
    return d


def _run_with_logger(
    args: argparse.Namespace,
    fn: Callable[[argparse.Namespace], Any],
) -> int:
    """Wrap a subcommand body with logger setup + JSON envelope emission.

    `fn` returns either a result dataclass / dict, or raises. On raise we
    capture the exception into the envelope and exit non-zero — never let
    a stack trace escape and corrupt the JSON line.
    """
    log_path = _logger.setup(verbose=getattr(args, "verbose", False))
    ok = True
    result_d: dict[str, Any] = {}
    try:
        result = fn(args)
        result_d = _result_dict(result)
        ok = bool(result_d.get("ok", True))
    except Exception as exc:
        log.exception("subcommand %r crashed", args.cmd)
        ok = False
        result_d = {
            "ok": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    finally:
        _logger.close(log_path)

    _emit({
        "ok": ok,
        "result": result_d,
        "log_path": str(log_path.relative_to(_REPO)),
    })
    return 0 if ok else 1


# ── subcommand handlers ──────────────────────────────────────────────────────

def _cmd_status(args: argparse.Namespace) -> Any:
    # status.py is pure-read; we skip the logger setup envelope entirely so
    # the snapshot doesn't pollute today's log with status queries.
    from pipeline.status import snapshot_dict
    return snapshot_dict(args.db)


def _cmd_health(args: argparse.Namespace) -> Any:
    """Lighter weight than `status` — just the health checks (ollama, env, disk).
    Designed for fast polling by /syndicate-heal."""
    from pipeline.status import snapshot
    snap = snapshot(args.db)
    return {
        "ok": (
            snap.ollama_reachable
            and snap.disk_free_gb > 1.0
            and snap.db_exists
        ),
        "ollama_reachable":     snap.ollama_reachable,
        "ollama_models_loaded": snap.ollama_models_loaded,
        "disk_free_gb":         snap.disk_free_gb,
        "db_exists":            snap.db_exists,
        "env_present":          snap.env_present,
        "git_branch":           snap.git_branch,
        "git_dirty":            snap.git_dirty,
        "errors":               snap.errors,
    }


def _cmd_ingest_gmail(args: argparse.Namespace) -> Any:
    from pipeline.ingestion.gmail import GmailPipeline
    return GmailPipeline(db_path=args.db).run(
        days=args.days, folder=args.folder, dump_json=args.dump_json,
    )


def _cmd_ingest_rss(args: argparse.Namespace) -> Any:
    from pipeline.ingestion.rss import RssPipeline
    return asyncio.run(
        RssPipeline(db_path=args.db).run(
            days=args.days, do_fetch=not args.no_fetch, dump_json=args.dump_json,
        )
    )


def _cmd_ingest_twitter(args: argparse.Namespace) -> Any:
    import os
    if args.headless is not None:
        os.environ["TWITTER_HEADLESS"] = "true" if args.headless else "false"
    from pipeline.ingestion.twitter import TwitterPipeline
    return asyncio.run(TwitterPipeline(db_path=args.db).run(days=args.days))


def _cmd_link(args: argparse.Namespace) -> Any:
    from pipeline.relation.linker import RelationLinker
    return RelationLinker(db_path=args.db).run()


def _cmd_dedup(args: argparse.Namespace) -> Any:
    from pipeline.dedup.runner import DedupPipeline
    tiers = tuple(int(t) for t in args.tiers.split(",")) if args.tiers else (1, 2, 3, 4)
    return DedupPipeline(db_path=args.db).run(
        window_days=args.window,
        tiers=tiers,
        t3_max_hamming=args.t3_hamming,
        t4_threshold=args.t4_threshold,
    )


def _cmd_summarize(args: argparse.Namespace) -> Any:
    from pipeline.AI.summarize import SummarizePipeline
    return SummarizePipeline(db_path=args.db, model=args.model).run(limit=args.limit)


def _cmd_export(args: argparse.Namespace) -> Any:
    from pipeline.git_export import GitExport
    return GitExport(db_path=args.db).run()


def _cmd_notify(args: argparse.Namespace) -> Any:
    """Read an OrchestratorResult JSON from stdin and notify Telegram.

    The skill body pipes the output of a prior `cli run` (or fetches the
    last run from the DB and constructs an equivalent payload) into this
    subcommand. Returns the bool result wrapped in {"ok": ...}.
    """
    from pipeline.channel.telegram import TelegramNotifier
    from pipeline.orchestrator import OrchestratorResult

    payload = sys.stdin.read().strip()
    if not payload:
        return {"ok": False, "errors": ["no input on stdin — pipe an OrchestratorResult JSON"]}
    try:
        data = json.loads(payload)
        # Accept either the cli envelope ({"result": {...}}) or a raw dataclass dict.
        if isinstance(data.get("result"), dict):
            data = data["result"]
        # OrchestratorResult requires started_at + finished_at + ok at minimum.
        # Fill in missing optional fields so the dataclass constructor succeeds.
        data.setdefault("started_at", "")
        data.setdefault("finished_at", "")
        data.setdefault("ok", False)
        data.setdefault("errors", [])
        obj = OrchestratorResult(**{k: v for k, v in data.items()
                                     if k in OrchestratorResult.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError) as e:
        return {"ok": False, "errors": [f"stdin parse: {type(e).__name__}: {e}"]}

    sent = TelegramNotifier().notify(obj)
    return {"ok": sent}


def _cmd_run(args: argparse.Namespace) -> Any:
    """Run the full pipeline. Mirrors pipeline.orchestrator.main() but emits
    structured JSON instead of the boxed text summary. Telegram notify still
    fires by default (parity with `uv run syndicate`) — pass --no-notify to
    skip.
    """
    from dataclasses import asdict as _asdict

    from pipeline.channel.telegram import TelegramNotifier
    from pipeline.git_export import GitExport
    from pipeline.main import run as _run
    from pipeline.orchestrator import OrchestratorResult
    from pipeline.storage import now_iso

    started = now_iso()

    db_path = Path(args.db)
    # Optional DB restore from feed repo — mirrors orchestrator.py:185-187.
    if not db_path.exists():
        log.info("snapshot.db not found — attempting restore from feed repo")
        try:
            GitExport(args.db).restore_snapshot(db_path)
        except Exception as exc:
            log.warning("snapshot restore failed (continuing with empty DB): %s", exc)

    pipeline_result = _run(
        days=args.days,
        dedup_window=args.dedup_window,
        db_path=args.db,
        skip_gmail=args.skip_gmail,
        skip_rss=args.skip_rss,
        skip_twitter=args.skip_twitter,
        skip_dedup=False,
        skip_summarize=False,
        summarize_limit=args.summarize_limit,
    )

    git_d: dict | None = None
    if not args.skip_git:
        try:
            git_result = GitExport(args.db).run()
            git_d = _asdict(git_result)
        except Exception as exc:
            log.exception("Git export crashed")
            git_d = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}

    all_errors = list(pipeline_result.errors)
    if git_d and not git_d.get("ok"):
        all_errors.extend(git_d.get("errors", []))

    result = OrchestratorResult(
        started_at=started,
        finished_at=now_iso(),
        ok=not all_errors,
        gmail=pipeline_result.gmail,
        rss=pipeline_result.rss,
        twitter=pipeline_result.twitter,
        embed=pipeline_result.embed,
        relation=pipeline_result.relation,
        dedup=pipeline_result.dedup,
        summarize=pipeline_result.summarize,
        git=git_d,
        errors=all_errors,
    )

    if not args.no_notify:
        try:
            TelegramNotifier().notify(result)
        except Exception:
            log.exception("Telegram notify crashed (swallowed)")

    return result


# ── argparse wiring ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Unified CLI for the syndicate pipeline. Each subcommand "
                    "emits {ok, result, log_path} JSON on stdout.",
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH),
                   help=f"SQLite path (default: {DEFAULT_DB_PATH})")
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="DB counts, last run per channel, env health (read-only)")
    sub.add_parser("health", help="Ollama + disk + env presence (fast subset of status)")

    sp = sub.add_parser("ingest-gmail", help="Fetch Gmail newsletters")
    sp.add_argument("--days", type=int, default=1)
    sp.add_argument("--folder", default="INBOX")
    sp.add_argument("--dump-json", default=None)

    sp = sub.add_parser("ingest-rss", help="Fetch RSS feeds")
    sp.add_argument("--days", type=int, default=1)
    sp.add_argument("--no-fetch", action="store_true",
                    help="Only re-process already-fetched HTML; skip network")
    sp.add_argument("--dump-json", default=None)

    sp = sub.add_parser("ingest-twitter", help="Scrape tweets via Playwright")
    sp.add_argument("--days", type=int, default=2)
    sp.add_argument("--headless", type=lambda s: s.lower() in ("1", "true", "yes"),
                    default=None,
                    help="Override TWITTER_HEADLESS env (true/false)")

    sub.add_parser("link", help="Run relation linker")

    sp = sub.add_parser("dedup", help="Run T1-T4 dedup across the dedup window")
    sp.add_argument("--window", type=int, default=10)
    sp.add_argument("--tiers", default="1,2,3,4",
                    help='Comma-separated tier list, e.g. "1,2,3,4"')
    sp.add_argument("--t3-hamming", type=int, default=3)
    sp.add_argument("--t4-threshold", type=float, default=0.60)

    sp = sub.add_parser("summarize", help="Run AI summarizer")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--model", default=None, help="Per-run model override")

    sub.add_parser("export", help="Export today's + window-days to news-archive and push")

    sub.add_parser("notify", help="Pipe OrchestratorResult JSON on stdin → Telegram")

    sp = sub.add_parser("run", help="Full pipeline (parity with `uv run syndicate`)")
    sp.add_argument("--days", type=int, default=2,
                    help="Ingestion lookback in days")
    sp.add_argument("--dedup-window", type=int, default=10)
    sp.add_argument("--summarize-limit", type=int, default=50)
    sp.add_argument("--skip-gmail", action="store_true")
    sp.add_argument("--skip-rss", action="store_true")
    sp.add_argument("--skip-twitter", action="store_true")
    sp.add_argument("--skip-git", action="store_true")
    sp.add_argument("--no-notify", action="store_true",
                    help="Skip Telegram notify (default: notify if configured)")

    return p


_HANDLERS: dict[str, Callable[[argparse.Namespace], Any]] = {
    "status":         _cmd_status,
    "health":         _cmd_health,
    "ingest-gmail":   _cmd_ingest_gmail,
    "ingest-rss":     _cmd_ingest_rss,
    "ingest-twitter": _cmd_ingest_twitter,
    "link":           _cmd_link,
    "dedup":          _cmd_dedup,
    "summarize":      _cmd_summarize,
    "export":         _cmd_export,
    "notify":         _cmd_notify,
    "run":            _cmd_run,
}

# Subcommands that should NOT spin up file logging — they're either
# pure-read (status, health) or read stdin (notify).
_NO_LOGGER_CMDS = {"status", "health", "notify"}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    handler = _HANDLERS[args.cmd]

    if args.cmd in _NO_LOGGER_CMDS:
        # Skip the full logger envelope — emit the JSON directly.
        ok = True
        try:
            result_d = _result_dict(handler(args))
            ok = bool(result_d.get("ok", True))
        except Exception as exc:
            log.exception("subcommand %r crashed", args.cmd)
            ok = False
            result_d = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}
        _emit({"ok": ok, "result": result_d, "log_path": None})
        return 0 if ok else 1

    return _run_with_logger(args, handler)


if __name__ == "__main__":
    sys.exit(main())
