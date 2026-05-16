---
name: syndicate-ingest-rss
description: Fetch RSS feeds from the last N days into syndicate's snapshot.db. Writes to DB.
when_to_use: |
  When the user explicitly asks to refresh / fetch / ingest RSS feeds into
  syndicate. Examples: "pull RSS", "refresh syndicate rss", "ingest the
  last 3 days of RSS".
argument-hint: "[--days 2] [--no-fetch]"
arguments:
  - name: days
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli ingest-rss*)
  - Bash(cd:*)
context: fork
---

# /syndicate-ingest-rss

You are running RSS ingestion. This **writes to the DB** — only run when the user explicitly asked.

## Step 1 — ingest
Default lookback is 1 day. Parse `$ARGUMENTS` for `--days N` (default 1) and
the boolean `--no-fetch` flag (default off — only re-parses already-cached
HTML instead of hitting the network):

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli ingest-rss --days ${days:-1} ${no_fetch:+--no-fetch}

Output envelope:

```json
{"ok": true, "result": {"fetched": N, "saved": N, "skipped": N, "failed": N, "errors": []}, "log_path": "logs/<date>.txt"}
```

## Step 2 — report
One line:

    ✓ rss · fetched=X saved=Y skipped=Z failed=W

If `failed > 0` or specific feeds appear in `result.errors`, list them.
A single feed returning 502 / 404 is non-fatal — syndicate's RSS pipeline
treats per-feed failures as `failed += 1` and continues. Surface the
failing feed name so the user can decide whether to remove it from
`config/rss_sources.json`.
