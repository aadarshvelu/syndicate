# Syndicate — project context for Claude sessions

## What this is

AI-powered daily news digest pipeline. Ingests from Gmail (newsletters) + RSS feeds + Twitter/X,
deduplicates, summarizes via Ollama, exports feed JSON to a sibling GitHub repo (`news-archive`).
PWA frontend (React + Vite) reads from that JSON and presents a swipeable card feed.

## Entry points

```bash
uv run syndicate          # daily driver — today + yesterday, full pipeline
uv run digest             # lower-level, all skip-* flags exposed
```

`syndicate` → `pipeline/orchestrator.py`
`digest` → `pipeline/main.py`

## Pipeline flow

```
[pre-flight GitExport — orphan summaries from prior runs]
  → Gmail.run(days=2) → RSS.run(days=2) → Twitter.run(days=2)
  → semantic.ensure_recent_embeddings(window=10)
  → Dedup.run(window=10)
  → RelationLinker.run()
  → Summarize.run()
  → [final GitExport in try/finally — runs even if pipeline crashed]
  → TelegramNotifier.notify()
```

Pre-flight + finally export = "PWA never sits on stale data because the
last run died before reaching git push." See "Resilience patterns" below.

## Key files

```
pipeline/
  orchestrator.py          — syndicate entry; hardcoded days=2, dedup_window=10; table summary output
                             flags: --skip-gmail --skip-rss --skip-twitter --skip-git
                             pre-flight + try/finally export (final export survives KeyboardInterrupt / SIGTERM)
  main.py                  — digest entry; all --skip-* flags
                             wires ensure_recent_embeddings stage between ingest and dedup
  cli.py                   — JSON-emitting per-stage CLI used by Claude Code skills
                             subcommands: status, health, ingest-{gmail,rss,twitter}, link-relations,
                                          dedup, summarize, export, run
  status.py                — read-only snapshot for /syndicate-status and /syndicate-heal
                             reads runs table for last_run_per_channel; checks ollama, disk, env
  budget.py                — BudgetWatch.for_stage(label); env BUDGET_<LABEL>_SEC
                             defaults: summarize=3600, ensure_embeddings=1800; 0 disables
  storage.py               — SQLite ItemStore; db/snapshot.db
                             columns: relation (null|standalone|reaction), parent_item_id FK
  logger.py                — logs/<date>.txt; IST+UTC timestamps; 7-day purge; session markers
                             playwright silenced to WARNING
  git_export.py            — export to news-archive repo; snapshot.db backup; PAT auth
  clean.py                 — HTML→text helpers
  ingestion/
    gmail.py, rss.py       — ingest channels
    twitter.py             — Playwright scraper; persistent Chrome profile (SyndicateBrowser)
                             env: CHROME_EXECUTABLE, CHROME_PROFILE_DIR, TWITTER_HEADLESS,
                                  TWITTER_MAX_TWEETS (15), TWITTER_LOOKBACK_DAYS (2)
                             burst merge: _merge_bursts() groups tweets <30min apart
                             login: uv run python -m pipeline.tools.test_twitter --login
    normalize.py           — unified item schema
    fetch.py               — async article fetch + OG image
    sources.py             — config/sources.json loader
  relation/
    linker.py              — RelationLinker; embeds tweets + news; cosine >0.72
                             standalone: tweet predates news OR no match
                             reaction: tweet posted after matching news (parent_item_id set)
                             window: 7 days; idempotent (skips relation IS NOT NULL)
  dedup/
    runner.py              — DedupPipeline; 4-tier + 2-phase
                             encoding-on-the-fly is now a FALLBACK; ensure_recent_embeddings
                             is expected to have pre-cached embeddings before this runs
    semantic.py            — provider-agnostic embeddings (EMBEDDING_PROVIDER/EMBEDDING_MODEL)
                             exports ensure_recent_embeddings(store, days) — runs as its own stage
                             pre-dedup; cosine on L2-normalized vectors; timeout 180s
  AI/
    summarize.py           — SummarizePipeline via DSPy + LiteLLM (any provider)
                             circuit breaker: 5 consecutive provider errors → bail, defer rest
                             wall-clock budget via BUDGET_SUMMARIZE_SEC (default 3600s)
    lm.py                  — _PROVIDERS table maps AI_PROVIDER → (litellm_prefix, default_model, api_key_env)
  tools/
    test_twitter.py        — smoke test; --handles --days --save --login flags
    simulate.py, smoke.py, smoke_rss.py

Front-end/
  src/
    App.jsx                — root; loads items from IndexedDB; lifted FullArticleSheet here (z-index fix)
                             personalization: IndexedDB likes → time-decay scores → sort unread feed
    components/
      AppShell.jsx         — desktop: IPhoneFrame (393px, fake status bar h=44, no home indicator)
                             mobile: fixed inset + paddingTop: env(safe-area-inset-top)
      LoadingScreen.jsx    — Three.js scene (ParticleField, NewsPlanes, Rings, Core); dark bg; zIndex 200
      BottomNav.jsx        — h=calc(60px + env(safe-area-inset-bottom)); corner fillers (semi-circle);
                             gooey pill; buttons constrained to top 60px
      FeedStack.jsx        — stack of up to 3 NewsCards; swipe history; "all caught up" state
                             filterCategory prop: reorders matched items first + AnimatePresence fade
      NewsCard.jsx         — swipe left=next, right=prev, up=expand; progress bar 15s auto-advance
                             iOS red #FF3B30 bar; Ken Burns 4-stop keyframes; hero 38% height
                             data-action escape hatch for buttons inside pointer-capturing card
                             Track (bookmark) + Share + Full Story buttons; onLike double-tap
      FullArticleSheet.jsx — Bebas Neue red title, Playfair italic teaser; createPortal full-screen reader
                             skeleton loading + red shimmer progress bar; iframe + shield div close fix
      ReadStack.jsx        — read items list
    db/
      schema.js            — IndexedDB v2; stores: items, meta, likes
      store.js             — upsertItems, getAllItems, markRead, storeLike, getPreferenceScores
                             DECAY_LAMBDA=0.1 (~7-day half-life); LIKES_CAP=500
      sync.js              — syncFeed; registerSyncListener; registerPeriodicSync
    hooks/
      useDeviceType.js     — isDesktop detection
    sw/
      sw.js                — Vite PWA injectManifest service worker
  public/
    favicon.svg            — dark square rx=7 + red S-curve stroke (#FA2D48)
    pwa-icon.svg           — PWA any icon
    pwa-icon-maskable.svg  — PWA maskable icon
  index.html               — viewport-fit=cover; Geist + Inter + Playfair fonts (Google Fonts)
  vite.config.js           — base '/syndicate/'; VitePWA injectManifest; SVG icons

scripts/
  setup_agent.sh           — one-time Mac setup: uv sync + install-browsers + X login + launchd plist
                             plist sets TWITTER_HEADLESS=true for automated runs
  run_syndicate.sh         — cron runner; TWITTER_HEADLESS inherited from plist env
                             calls free_memory.sh BEFORE syndicate (Quit Cursor/MCP, restart Ollama)
  free_memory.sh           — RAM cleanup; opt-out via SYNDICATE_SKIP_FREE_MEMORY=1
  clean_stale_runs.sh      — kills syndicate processes elapsed > THRESHOLD_SEC=28800 (8h)
                             threshold was 4h pre-May-2026 and killed legitimate slow runs mid-summarize
  watchdog.py              — standalone freshness check; reads runs table directly (no pipeline imports
                             so it works even if pipeline code is broken). Pings Telegram if any
                             channel finished_at > 24h ago. Skip a channel via WATCHDOG_SKIP_<CH>=1

  syndicate.plist          — launchd at 11:59 and 23:59 IST
  syndicate.cleaner.plist  — clean_stale_runs.sh at 09:00 and 21:00 IST
                             (was 06:00/18:00 — that was killing slow runs at the 6h mark)
  syndicate.watchdog.plist — watchdog.py at 00:30, 06:30, 12:30, 18:30 IST

.github/workflows/deploy.yml  — push-to-main → npm ci --legacy-peer-deps → build → GitHub Pages
```

## DB

- Path: `db/snapshot.db`
- Bootstrap: if missing on start, orchestrator calls `GitExport.restore_snapshot()` to clone
  news-archive and copy backup
- `content != ''` guard in `items_needing_summary` — some sources return empty body
- `relation` column: `null` = unprocessed, `standalone` = tweet is the story, `reaction` = tweet reacts to news
- `parent_item_id` column: FK to items.id, set when relation=reaction

## Config

- `config/sources.json` — Gmail source registry
- `config/rss_sources.json` — RSS feeds
- `config/twitter_sources.json` — 18 Twitter handles (sama, ylecun, emollick, simonw, etc.)

## Env vars (`.env`)

```
GMAIL_USER=
GMAIL_APP_PASSWORD=
AI_PROVIDER=                 # ollama (default) | anthropic | openai | gemini | minimax
SUMMARIZE_MODEL=             # provider-native, optional (has per-provider defaults)
EMBEDDING_MODEL=             # provider-native, optional (has per-provider defaults)
EMBEDDING_PROVIDER=          # optional, defaults to AI_PROVIDER. Required when AI_PROVIDER=anthropic|minimax
OLLAMA_HOST=                 # used iff AI_PROVIDER or EMBEDDING_PROVIDER is ollama
ANTHROPIC_API_KEY=           # iff AI_PROVIDER=anthropic
OPENAI_API_KEY=              # iff AI_PROVIDER=openai or EMBEDDING_PROVIDER=openai
GEMINI_API_KEY=              # iff AI_PROVIDER=gemini or EMBEDDING_PROVIDER=gemini
MINIMAX_API_KEY=             # iff AI_PROVIDER=minimax
VOYAGE_API_KEY=              # iff EMBEDDING_PROVIDER=voyage
COHERE_API_KEY=              # iff EMBEDDING_PROVIDER=cohere
FEED_REPO_URL=               # https://github.com/aadarshvelu/news-archive.git
FEED_REPO_PAT=               # GitHub PAT, public_repo scope
CHROME_EXECUTABLE=           # auto-detected if not set; Windows path checked for existence first
CHROME_PROFILE_DIR=          # default: SyndicateBrowser (Win) / ~/.syndicate-browser (Mac)
TWITTER_HEADLESS=            # false for dev; true injected by launchd plist for automated runs
TWITTER_MAX_TWEETS=          # default: 15

# A–F resilience knobs (optional — defaults are sensible)
BUDGET_SUMMARIZE_SEC=        # default 3600; 0 disables. Per-iteration polling, not signal-based
BUDGET_ENSURE_EMBEDDINGS_SEC=  # default 1800; 0 disables
WATCHDOG_STALE_HOURS=        # default 24; watchdog.py alerts if any channel older than this
WATCHDOG_SKIP_TWITTER=       # set to 1 to skip that channel in the freshness check
SYNDICATE_SKIP_FREE_MEMORY=  # set to 1 to skip free_memory.sh in run_syndicate.sh
```

No `FEED_REPO_PATH` — local clone path auto-derived from URL as sibling of syndicate dir.

## Feed JSON (news-archive)

Path: `<year>/<MonthName>/<day>-<Mon>-<YY>.json`  e.g. `2026/May/3-May-26.json`

Fields: `id, cluster_id, cluster_size, source, title, teaser, summary, importance, category, url, date, image_url`

## Git repos

- `https://github.com/aadarshvelu/syndicate.git` — this codebase
- `https://github.com/aadarshvelu/news-archive.git` — feed JSON output + snapshot.db backup

## Logging

All entrypoints call `pipeline.logger.setup()` at start and `pipeline.logger.close(log_path)`
in `finally`. Log files in `logs/<YYYY-MM-DD>.txt`. Noisy libs silenced: readability, httpcore,
urllib3, chardet, playwright.

## Resilience patterns (A–F refactor, May 2026)

Triggered by a 5-day silent outage where runs were dying mid-summarize
(cleaner killing them at the 4h mark, Ollama OOM under memory pressure)
and the PWA was sitting on stale data while the laptop hoarded
unpushed summaries. Six independent fixes:

| Letter | Pattern | Where it lives |
|---|---|---|
| **A** | Pre-flight export + try/finally final export, KeyboardInterrupt-safe | `pipeline/orchestrator.py` |
| **B** | Per-stage wall-clock budgets polled between iterations | `pipeline/budget.py` |
| **C** | `ensure_recent_embeddings` runs before dedup → dedup ~3h → ~1s | `pipeline/dedup/semantic.py`, wired in `pipeline/main.py` |
| **D** | Standalone watchdog reads runs table, pings Telegram on staleness | `scripts/watchdog.py` + `scripts/syndicate.watchdog.plist` |
| **E** | Cleaner threshold 4h → 8h, schedule 06:00/18:00 → 09:00/21:00 | `scripts/clean_stale_runs.sh` + `scripts/syndicate.cleaner.plist` |
| **F** | Summarize circuit breaker — bail on 5 consecutive provider errors | `pipeline/AI/summarize.py` (`_BREAKER_THRESHOLD`, `_is_provider_error`) |

Per-letter validation is documented in the relevant module's doc.md.

## Key decisions

- Summarize model: `gemma4:latest` (benchmark winner for PWA teaser style)
- Embed model: `qwen3-embedding:latest` via Ollama HTTP; timeout 180s; cached in items.embedding BLOB
- Dedup: 4 tiers (T1 exact URL/title, T2 fuzzy+date, T3 simhash, T4 semantic cosine ≥0.60)
- Twitter: Playwright persistent context (SyndicateBrowser profile); explicit chrome.exe path
  CHROME_EXECUTABLE env var checked for existence before use (handles cross-platform .env)
- RelationLinker: similarity threshold 0.72; standalone if tweet predates news or no match
- JSON stdout replaced with human-readable table summary in orchestrator
- No Co-Authored-By Claude in any commit (public repos)
- PWA deploy: GitHub Pages at `/syndicate/`; `npm ci --legacy-peer-deps` (vite-plugin-pwa@1.2.0 / vite@8 peer conflict)
- FullArticleSheet lifted to App.jsx level (z-index 300) — card stacking context would otherwise trap it below BottomNav (z-index 50)
- Corner gap between card and nav filled with two 20×40 overflow-hidden semi-circle divs at `top: -20` of nav
- LoadingScreen: Math.random moved to module-level IIFEs (linter bars it inside render); `{visible && (` is correct — linter occasionally inverts to `!visible`, must manually fix
- AppShell desktop fake status bar height: 44px (matches Dynamic Island bottom at top:12 + h:28 = 40px)
- No home indicator in desktop IPhoneFrame (removed)
- Personalization: IndexedDB `likes` store; time-decay λ=0.1; category weight ×2; 500-entry cap
- Category filter overrides personalization sort (FeedStack reorder after App sort)
