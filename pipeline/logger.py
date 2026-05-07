"""Centralized logging: writes to logs/<date>.txt, auto-purges files older than 7 days."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"
_KEEP_DAYS = 7
_SEP = "=" * 72
_start_times: dict[Path, datetime] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _purge_old() -> None:
    if not _LOGS_DIR.exists():
        return
    cutoff = _now_utc().date() - timedelta(days=_KEEP_DAYS)
    for f in _LOGS_DIR.glob("????-??-??.txt"):
        try:
            if datetime.strptime(f.stem, "%Y-%m-%d").date() < cutoff:
                f.unlink()
        except ValueError:
            pass


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def setup(*, verbose: bool = False) -> Path:
    """
    Configure root logger. Creates or appends to logs/<today>.txt.
    Returns the log file path — pass it to close() at the end of the run.

    File always receives DEBUG+. Stderr receives INFO (or DEBUG if verbose).
    Uncaught exceptions are captured via sys.excepthook.
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _purge_old()

    now_utc = _now_utc()
    now_local = datetime.now().astimezone()
    today = now_utc.strftime("%Y-%m-%d")
    log_path = _LOGS_DIR / f"{today}.txt"
    utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    tz_name = now_local.strftime("%Z") or now_local.strftime("%z")
    local_str = now_local.strftime(f"%Y-%m-%d %H:%M:%S {tz_name}")
    ts = f"{local_str}  ({utc_str})"

    _start_times[log_path] = now_utc

    # 4 blank lines then start separator
    _append(log_path, f"\n\n\n\n{_SEP}\n{ts}  START\n{_SEP}\n")

    file_handler = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stderr_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    # Silence noisy third-party libraries
    for _noisy in ("readability", "readability.readability", "httpcore",
                   "urllib3", "chardet", "charset_normalizer",
                   "playwright", "playwright._impl"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("uncaught").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _excepthook

    return log_path


def close(log_path: Path) -> None:
    """Flush handlers, then write 3 blank lines + end separator."""
    for h in logging.getLogger().handlers:
        h.flush()
    now_utc = _now_utc()
    now_local = datetime.now().astimezone()
    utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    tz_name = now_local.strftime("%Z") or now_local.strftime("%z")
    local_str = now_local.strftime(f"%Y-%m-%d %H:%M:%S {tz_name}")
    elapsed = _now_utc() - _start_times.pop(log_path, now_utc)
    secs = int(elapsed.total_seconds())
    dur = f"{secs // 60}min {secs % 60}sec"
    ts = f"{local_str}  ({utc_str})  {dur}"
    _append(log_path, f"\n\n\n{_SEP}\n{ts}  END\n{_SEP}\n")
