---
name: syndicate-run
description: Run the full syndicate pipeline end-to-end — ingest (gmail+rss+twitter) → link → dedup → summarize → export → notify. Parity with `uv run syndicate`.
when_to_use: |
  When the user asks to "run syndicate", "do a full run", "run the
  pipeline end-to-end". Equivalent to the launchd 11:58/23:58 schedule
  but invokable on demand.
argument-hint: "[--skip-gmail] [--skip-rss] [--skip-twitter] [--skip-git] [--summarize-limit 50]"
arguments:
  - name: skip_gmail
    type: bool
    required: false
  - name: skip_rss
    type: bool
    required: false
  - name: skip_twitter
    type: bool
    required: false
  - name: skip_git
    type: bool
    required: false
  - name: summarize_limit
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli run*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: fork
---

# /syndicate-run

You are running the full syndicate pipeline. **Long-running** (typically
30–90 min depending on backlog and AI provider) and **writes to the DB**
plus **pushes to the news-archive git remote**. Only run when the user
explicitly asked.

This is the on-demand equivalent of the user's scheduled cron. It does
**not** schedule the next wake-up — scheduling is the user's local concern
(launchd / systemd / cron / etc.) and is documented in the README.

## Step 1 — preflight
Run `status` once before kicking off:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli status

Report `items_unsummarized` and the current `last_run_per_channel.<ch>.ok`
flags. If any required env var (per the `/syndicate-heal` recommended-vars
list) is missing, **stop and report** — the run will fail mid-flight
otherwise.

## Step 2 — run
Parse `$ARGUMENTS` for skip flags and `--summarize-limit N`:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli run \
        ${skip_gmail:+--skip-gmail} \
        ${skip_rss:+--skip-rss} \
        ${skip_twitter:+--skip-twitter} \
        ${skip_git:+--skip-git} \
        --summarize-limit ${summarize_limit:-50}

The output envelope contains a full OrchestratorResult dict:

```json
{
  "ok": true,
  "result": {
    "started_at": "...",
    "finished_at": "...",
    "ok": true,
    "gmail":     {"ok": true, "fetched": N, "saved": N, ...},
    "rss":       {...},
    "twitter":   {...},
    "relation":  {...},
    "dedup":     {...},
    "summarize": {...},
    "git":       {"ok": true, "exported_today": N, "committed": true, "pushed": true, ...},
    "errors": []
  },
  "log_path": "logs/<date>.txt"
}
```

By default the run also posts a summary to Telegram (matches `uv run
syndicate` behavior). Pass `--no-notify` if the user wants to skip that.

## Step 3 — report
Render the standard box summary that the user is familiar with from the
launchd run output and from Telegram:

```
════════════════════════════════════════════════════════════════════
  SYNDICATE  ·  <finished_at>  ·  <duration>  ·  <OK|FAILED>
════════════════════════════════════════════════════════════════════
  ✓  Gmail         fetched=N saved=N skipped=N failed=N
  ✓  RSS           fetched=N saved=N skipped=N failed=N
  ✓  Twitter       fetched=N saved=N skipped=N failed=N
  ✓  Relation      examined=N standalone=N reactions=N
  ✓  Dedup         examined=N clusters=N demoted=N [method=N ...]
  ✓  Summarize     examined=N done=N skipped=N
  ✓  Git           today=+N yesterday=+N · committed · pushed
════════════════════════════════════════════════════════════════════
```

If `errors` is non-empty, append an `ERRORS:` section with each one on
its own line. Recommend `/syndicate-heal` if the failure pattern looks
like infrastructure (Ollama, IMAP, git push).
