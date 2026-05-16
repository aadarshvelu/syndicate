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
Gmail.run(days=2) → RSS.run(days=2) → Twitter.run(days=2)
  → RelationLinker.run() → Dedup.run(window=10) → Summarize.run() → GitExport.run()
```

## Key files

```
pipeline/
  orchestrator.py          — syndicate entry; hardcoded days=2, dedup_window=10; table summary output
                             flags: --skip-gmail --skip-rss --skip-twitter --skip-git
  main.py                  — digest entry; all --skip-* flags
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
    semantic.py            — Ollama embeddings; cosine similarity; timeout 180s
  AI/
    summarize.py           — SummarizePipeline; Ollama /api/chat; gemma4:latest
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
