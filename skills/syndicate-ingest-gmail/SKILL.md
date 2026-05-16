---
name: syndicate-ingest-gmail
description: Fetch Gmail newsletters from the last N days into syndicate's snapshot.db. Writes to DB.
when_to_use: |
  When the user explicitly asks to refresh / fetch / ingest Gmail newsletters
  into syndicate. Examples: "pull Gmail newsletters", "refresh syndicate gmail",
  "ingest the last 3 days of gmail".
argument-hint: "[--days 2] [--folder INBOX]"
arguments:
  - name: days
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli ingest-gmail*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: fork
---

# /syndicate-ingest-gmail

You are running Gmail ingestion. This **writes to the DB** — only run when the user explicitly asked.

## Step 1 — preflight
Check `GMAIL_USER` and `GMAIL_APP_PASSWORD` are set by running `status` first:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli status

If `result.env_present.GMAIL_USER` or `result.env_present.GMAIL_APP_PASSWORD`
is `false`, tell the user which one is missing and stop. Do not attempt the
ingest.

## Step 2 — ingest
Default lookback is 1 day. Parse `$ARGUMENTS` for `--days N` if supplied
(otherwise use 1) and `--folder NAME` (otherwise INBOX):

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli ingest-gmail --days ${days:-1} --folder ${folder:-INBOX}

The output envelope is:

```json
{"ok": true, "result": {"fetched": N, "saved": N, "skipped": N, "failed": N, "errors": []}, "log_path": "logs/<date>.txt"}
```

## Step 3 — report
Render one line:

    ✓ gmail · fetched=X saved=Y skipped=Z failed=W

If `failed > 0` or `result.ok` is `false`, also dump the first 3 entries
from `result.errors`. Suggest `/syndicate-heal` if the failure pattern
looks like IMAP timeouts or auth failure.
