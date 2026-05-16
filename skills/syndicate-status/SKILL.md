---
name: syndicate-status
description: Show current syndicate pipeline state — DB counts, last run per channel, log tail, env health. Read-only.
when_to_use: |
  When the user asks about the state of the syndicate pipeline:
  "what's the state of syndicate", "did the last run work",
  "how many items did we get today", "is ollama up for syndicate",
  "syndicate status".
disable-model-invocation: false
allowed-tools:
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: inline
---

# /syndicate-status

You are inspecting the syndicate pipeline. Do **not** mutate state.

## Step 1 — locate the repo
Resolve `$SYNDICATE_REPO`. If unset, fall back to `$(pwd)` and verify a
`pipeline/` directory exists there. If neither resolves, tell the user to
`export SYNDICATE_REPO=/path/to/syndicate` in their shell rc and stop.

## Step 2 — fetch the snapshot
Run exactly:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli status

The command emits a single JSON object on stdout:

```json
{
  "ok": true,
  "result": {
    "db_path": "db/snapshot.db",
    "db_exists": true,
    "db_size_bytes": 12345678,
    "items_total": 1234,
    "items_last_24h": 42,
    "items_unsummarized": 7,
    "clusters_total": 89,
    "last_run_per_channel": {
      "gmail":   {"finished_at": "...", "ok": true,  "fetched": 12, ...},
      "rss":     {...},
      "twitter": {...}
    },
    "log_path_today": "logs/2026-05-15.txt",
    "log_tail": ["...", "..."],
    "disk_free_gb": 42.1,
    "ollama_reachable": true,
    "env_present": {"GMAIL_USER": true, "ANTHROPIC_API_KEY": false, ...},
    "git_branch": "main",
    "git_dirty": false
  },
  "log_path": null
}
```

Schema definition: [`pipeline/status.py`](../../pipeline/status.py) `StatusSnapshot`.

## Step 3 — render
Produce a compact, scannable summary:

- **Header**: `syndicate · <items_total> items · +<items_last_24h> 24h · <clusters_total> clusters · <items_unsummarized> pending`
- **Per-channel table**: one row each for gmail / rss / twitter from
  `last_run_per_channel`. Format: `✓ gmail · 12 saved · 2h ago` or
  `✗ rss · failed: 502 (3h ago)`.
- **Health**: bullet any of these that are red:
  - `ollama_reachable` is `false`
  - `disk_free_gb < 5`
  - any required env var in `env_present` is `false` (`GMAIL_USER`,
    `FEED_REPO_URL`, `OLLAMA_HOST` for the default stack)
  - `git_dirty` is `true` (advisory only)
- **Last log lines**: include the last 5 entries of `log_tail` **only** if
  the most recent channel run failed, otherwise omit entirely.

If the JSON cannot be parsed, dump stderr verbatim and stop. Do not retry.
