"""Standalone entrypoint for the summarize pipeline.

Usage:
  uv run python -m pipeline.AI.summarize_pipeline
  uv run python -m pipeline.AI.summarize_pipeline --limit 10 -v
  uv run python -m pipeline.AI.summarize_pipeline --model gemma3:4b
  uv run python -m pipeline.AI.summarize_pipeline --model llama3.2:3b --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

from pipeline import logger as _logger
from pipeline.AI.summarize import SummarizePipeline
from pipeline.storage import DEFAULT_DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize pipeline — enrich items with AI teaser/summary")
    parser.add_argument("--limit", type=int, default=100, help="Max items to process (default 100)")
    parser.add_argument("--model", default=None, help="Ollama model override (e.g. gemma3:4b)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_path = _logger.setup(verbose=args.verbose)
    try:
        result = SummarizePipeline(db_path=args.db, model=args.model).run(limit=args.limit)
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1
    finally:
        _logger.close(log_path)


if __name__ == "__main__":
    sys.exit(main())
