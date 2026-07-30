---
name: syndicate-ingest-twitter
description: Fetch tweets via Playwright or Hermes Tweet/Xquik from the last N days. Writes to DB.
when_to_use: |
  When the user explicitly asks to refresh / fetch / scrape Twitter for
  syndicate. Examples: "pull tweets", "refresh syndicate twitter", "scrape
  the last 3 days".
argument-hint: "[--days 2] [--headless true]"
arguments:
  - name: days
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli ingest-twitter*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: fork
---

# /syndicate-ingest-twitter

You are running Twitter ingestion. The default backend uses a
Playwright-controlled Chrome profile. If `TWITTER_BACKEND=hermes_tweet`, the
skill fetches configured handles through Hermes Tweet/Xquik instead. This
**writes to the DB** and can launch Chrome on the default backend — only run
when the user explicitly asked.

## Step 1 — preflight
Run `status` and inspect `result.twitter_backend`.

If `result.twitter_backend` is `hermes_tweet` or `xquik`, check
`result.env_present.XQUIK_API_KEY`. If it is
`false`, tell the user to set `XQUIK_API_KEY` and stop.

If `result.twitter_backend` is `playwright`, check
`result.env_present.CHROME_EXECUTABLE` and
`result.env_present.CHROME_PROFILE_DIR`. If either is `false`, tell the user
how to set them (see syndicate's README) and stop. The Playwright scraper will
refuse to authenticate without a valid persistent profile.

For any other value, report the invalid backend and stop.

## Step 2 — scrape
Default lookback is 2 days. Parse `$ARGUMENTS` for `--days N` (default 2)
and `--headless true|false` (default true — matches launchd):

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli ingest-twitter --days ${days:-2} --headless ${headless:-true}

This can take 5–20 minutes depending on how many handles are configured
and how active they've been. The skill runs in a forked subagent context
so progress logs don't pollute the parent agent's history.

## Step 3 — report
One line:

    ✓ twitter · fetched=X saved=Y skipped=Z failed=W

If `failed > 0`, surface error patterns: strict-mode locator violations,
captcha pages, X.com rate limits, or persistent-profile auth loss all show
up here. For auth loss specifically, the remediation is to re-run
`scripts/setup_agent.sh` and re-do the manual X login.

Xquik is an independent third-party service. Not affiliated with X Corp. "Twitter" and "X" are trademarks of X Corp.
