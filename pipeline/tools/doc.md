# tools

Dev and debug scripts. None write to production state without explicit confirmation.

## simulate.py — day-by-day pipeline replay

```mermaid
flowchart TD
    A["simulate --confirm --fetch-days 30"] --> B["Collect all items upfront — Gmail + RSS"]
    B --> C["Group items by article date"]
    C --> D["Wipe DB — irreversible without backup"]
    D --> E["For each calendar day in range"]
    E --> F["Insert that day's items — ItemStore.insert_items()"]
    F --> G["DedupPipeline.run() — as_of = end of sim day"]
    G --> H["Print daily row — New/Gmail/RSS/Saved/Skip/Clusters"]
    H --> E
    E -->|done| I["Quality report — cluster distribution, tier effectiveness, sparkline"]
```

**Why collect first, then wipe?** All data is pulled from live sources before the DB is cleared. The replay inserts items one day at a time to simulate how the pipeline would behave in production with a rolling window.

**`as_of` anchor:** Without it, early sim days (e.g. 30 days ago) fall outside the live 10-day dedup window and report 0 examined. `as_of = end of sim day` makes the window relative to the simulated date.

## smoke.py — IMAP connection check

Connects to Gmail IMAP, searches recent UIDs, prints headers. No extraction, no DB writes. Use to verify auth and connectivity before running the full Gmail pipeline.

```bash
uv run python -m pipeline.tools.smoke --folder INBOX --days 3 --limit 20
```

## smoke_rss.py — RSS feed check

Fetches all feeds in `config/rss_sources.json`, optionally follows article URLs via readability. Prints entries with body previews. No DB writes. Use to verify feed URLs and `fetch_full` config.

```bash
uv run python -m pipeline.tools.smoke_rss --limit 3 -v
uv run python -m pipeline.tools.smoke_rss --no-fetch
```

## test_twitter.py — Twitter scraper smoke test

Drives `TwitterPipeline` against the configured handles (or a custom
list) and prints what would be inserted. No DB writes by default — pass
`--save` to actually persist into `db/snapshot.db`. Use to verify the
persistent Chrome profile + cookies after `setup_agent.sh`, or after
X.com changes its DOM and you're updating selectors.

```bash
uv run python -m pipeline.tools.test_twitter
uv run python -m pipeline.tools.test_twitter --handles karpathy simonw
uv run python -m pipeline.tools.test_twitter --save
```

## install_browsers.py — Playwright browser install

Thin wrapper that runs `playwright install chrome`. Exposed via the
`install-browsers` script entrypoint in `pyproject.toml`, so the
documented one-liner is:

```bash
uv run install-browsers
```

Run once after `uv sync` if you intend to use the Twitter pipeline.
Skip otherwise — RSS/Gmail don't need a browser.
