---
name: syndicate-heal
description: Diagnose syndicate health — ollama reachability, disk free, env vars, git state. Reports remediation hints; does NOT auto-fix.
when_to_use: |
  When the user reports a failure ("syndicate is broken", "pipeline didn't
  run", "telegram never sent the summary") or when /syndicate-status
  surfaces a red flag and you want to understand why.
disable-model-invocation: false
allowed-tools:
  - Bash(uv run python -m pipeline.cli health*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(launchctl list*)
  - Bash(ps -ef*)
  - Bash(pgrep*)
  - Bash(cd:*)
context: fork
---

# /syndicate-heal

You are diagnosing the syndicate pipeline. **Do not auto-fix anything** —
your job is to report what's wrong with actionable shell commands the user
can copy. The user takes the remediation step.

## Step 1 — health snapshot

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli health

Then fetch the broader status for context:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli status

## Step 2 — check for stuck processes
Look for syndicate processes that have been alive too long (≥4h is the
default cleaner threshold):

    pgrep -lf 'run_syndicate\.sh|uv run syndicate|\.venv/bin/syndicate'

For each PID, get elapsed time:

    ps -p <PID> -o etime=,command=

## Step 3 — diagnose & recommend

Walk through each signal in priority order and surface remediation hints:

### Ollama unreachable
- Symptom: `health.ollama_reachable = false`
- Likely cause: Ollama not running, or `OLLAMA_HOST=0.0.0.0` was injected
  by launchd (it can't be used as a client URL).
- Fix: `unset OLLAMA_HOST` (or set to `http://localhost:11434`), then
  `ollama serve` if the process isn't running.

### Required env var missing
- Walk `env_present` and flag any of these `false`: `GMAIL_USER`,
  `GMAIL_APP_PASSWORD`, `FEED_REPO_URL`, `FEED_REPO_PAT`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- For the AI provider, look at `env_present.AI_PROVIDER` (defaults to
  `ollama` if unset) and flag the matching credential as `false`:
  `ollama` → `OLLAMA_HOST`; `anthropic` → `ANTHROPIC_API_KEY`; `openai`
  → `OPENAI_API_KEY`; `gemini` → `GEMINI_API_KEY`; `minimax` →
  `MINIMAX_API_KEY`. If `EMBEDDING_PROVIDER` is set and differs, also
  check its credential.
- Fix: point them at the README's `.env` matrix and [`INSTALL.md`](../../INSTALL.md).

### Disk low
- Symptom: `disk_free_gb < 5`
- Fix: `find logs/ -name '*.txt' -mtime +7 -delete` (logger already does
  this for >7d files, but only when invoked).

### Stuck syndicate processes
- Symptom: pgrep shows a PID with elapsed time > 4h
- Fix: `bash scripts/clean_stale_runs.sh` — kills processes over the 4h
  threshold via SIGTERM with SIGKILL fallback. Mac-only (uses macOS `ps`).

### Last run failed
- From `status.last_run_per_channel`, find any channel with `ok=false`.
- Surface the `errors` array verbatim. Common ones:
  - `IMAP connect timed out` → Gmail outage or network; retry later
  - `feed <name>: HTTP 502` → that single feed is bad; remove from
    `config/rss_sources.json` if persistent
  - `playwright strict-mode locator violation` → X.com changed DOM;
    update selectors in `pipeline/ingestion/twitter.py`

### Git dirty (advisory only)
- If `status.git_dirty=true`, mention it but don't treat as blocker.
- Note: launchd-driven runs commit their own changes to `news-archive/`
  not to the syndicate repo itself.

## Step 4 — report
Produce a short list of red flags with the exact shell command to fix each.
End with `(rerun /syndicate-status to verify)`. **Do not run any
remediation command yourself** — the user runs them.
