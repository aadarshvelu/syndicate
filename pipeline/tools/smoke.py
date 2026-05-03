from __future__ import annotations

import argparse
import sys

from pipeline import logger as _logger
from pipeline.auth.gmail import session
from pipeline.ingestion.imap import fetch_message, get_header, search_uids


def main() -> int:
    parser = argparse.ArgumentParser(description="IMAP header smoke test")
    parser.add_argument("--folder", default="INBOX")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_path = _logger.setup(verbose=args.verbose)
    try:
        return _run(args)
    finally:
        _logger.close(log_path)


def _run(args) -> int:
    with session() as imap:
        typ, data = imap.select(f'"{args.folder}"', readonly=True)
        if typ != "OK":
            print(f"[error] could not select {args.folder!r}: {data!r}", file=sys.stderr)
            return 1
        print(f"[folder {args.folder!r} contains {int(data[0])} messages]\n", file=sys.stderr)

        uids = search_uids(imap, lookback_days=args.days)
        print(f"[{len(uids)} UIDs in last {args.days} day(s)]\n", file=sys.stderr)

        if not uids:
            print("No mail in window. Try larger --days.", file=sys.stderr)
            return 0

        for uid in uids[-args.limit :][::-1]:
            msg, _ = fetch_message(imap, uid)
            print("-" * 80)
            print(f"UID:     {uid.decode()}")
            print(f"From:    {get_header(msg, 'From')}")
            print(f"Subject: {get_header(msg, 'Subject')}")
            print(f"Date:    {get_header(msg, 'Date')}")
            print(f"To:      {get_header(msg, 'To')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
