<div align="center">

<h1>syndicate</h1>

<p>
  <b>Personal AI news archiver.</b> Runs on your laptop, summarizes with a
  local model, stores and serves through Git. Zero monthly cost.
</p>

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square&labelColor=black" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&labelColor=black&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/DSPy-✦-9D4EDD?style=flat-square&labelColor=black" alt="DSPy"/>
  <img src="https://img.shields.io/badge/Ollama-local-000000?style=flat-square&labelColor=black&logo=ollama" alt="Ollama"/>
  <img src="https://img.shields.io/badge/Claude_Code-Plugin-D97757?style=flat-square&labelColor=black&logo=anthropic&logoColor=white" alt="Claude Code Plugin"/>
  <a href="https://github.com/aadarshvelu/syndicate/stargazers"><img src="https://img.shields.io/github/stars/aadarshvelu/syndicate?style=flat-square&labelColor=black&color=ffcb47&logo=github" alt="Stars"/></a>
</p>

<p>
  <code>/plugin marketplace add aadarshvelu/syndicate</code>
  &nbsp;·&nbsp;
  <code>/plugin install syndicate-pipeline@syndicate</code>
</p>

</div>

<br />

> Every morning I'd open Gmail, scroll Twitter, hop over to Hacker News —
> and somehow read the same OpenAI announcement over and over while missing
> the small Anthropic update that actually mattered. Tabs full of the same
> story, none of the signal.
>
> Syndicate is the fix.

---

## 👋 Why this exists

The constraint that shaped the architecture was simple: **no server, no monthly bill.**
Which meant re-inventing the usual "Postgres + cron + S3 + CDN + Vercel" stack
as things I already had at home:

<table>
  <tr>
    <td>🧠</td>
    <td><b>Compute</b></td>
    <td>My laptop, on a regular schedule via <code>launchd</code>. No daemon, no always-on box. A missed cycle catches up cleanly within the rolling ingest window — longer absences lose older items.</td>
  </tr>
  <tr>
    <td>🤖</td>
    <td><b>AI</b></td>
    <td>A local small language model (Ollama-served <code>gemma4</code>) for summarization, a local embedding model for dedup. Zero API spend.</td>
  </tr>
  <tr>
    <td>📦</td>
    <td><b>Storage</b></td>
    <td>A second Git repo (<code>news-archive</code>) holds the daily JSON output. Versioned for free, no DB to host.</td>
  </tr>
  <tr>
    <td>🌐</td>
    <td><b>Hosting</b></td>
    <td>GitHub Pages serves the PWA. It fetches its data straight out of <code>news-archive</code>. No backend, no CDN bill.</td>
  </tr>
</table>

Total operational cost: electricity. Total infrastructure: my laptop and two Git repos.

---

## 🚀 Get started in 60 seconds

<table>
  <thead>
    <tr>
      <th>How to use it</th>
      <th>What you run</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>🧑‍💻 <b>Claude Code plugin</b><br/><sub>conversational, agent-driven</sub></td>
      <td>
        <pre><code>/plugin marketplace add aadarshvelu/syndicate
/plugin install syndicate-pipeline@syndicate
/syndicate-pipeline:syndicate-status</code></pre>
      </td>
    </tr>
    <tr>
      <td>⚙️ <b>Direct CLI</b><br/><sub>cron-friendly text output</sub></td>
      <td>
        <pre><code>git clone https://github.com/aadarshvelu/syndicate.git
cd syndicate &amp;&amp; uv sync
cp .env.example .env  # fill in what you need
uv run syndicate</code></pre>
      </td>
    </tr>
    <tr>
      <td>📱 <b>Read on phone/desktop</b><br/><sub>PWA, no install</sub></td>
      <td>
        <a href="https://aadarshvelu.github.io/syndicate/"><b>aadarshvelu.github.io/syndicate</b></a><br/>
        <sub>Works offline. Add to Home Screen for native-app feel.</sub>
      </td>
    </tr>
  </tbody>
</table>

Long-form install walkthrough, env-loading mechanics, and publishing notes
live in [INSTALL.md](INSTALL.md).

---

## 📱 Read the feed

<a href="https://aadarshvelu.github.io/syndicate/"><b>aadarshvelu.github.io/syndicate</b></a>
— static React/Vite PWA on GitHub Pages. Reads per-day JSON straight
from the [news-archive](https://github.com/aadarshvelu/news-archive)
repo, caches in IndexedDB, works offline once loaded. No accounts, no
backend, no data leaves the device.

<p align="center">
  <img src="docs/assets/pwa-screenshot.png" width="38%" alt="syndicate PWA — Unread feed showing an OpenAI voice-API card with reaction pills and category chip"/>
</p>

**Install it as a phone app** (takes 10 seconds):

<table>
  <tr>
    <td>📱 <b>iOS Safari</b></td>
    <td>Open the link → Share → <b>Add to Home Screen</b> → Add</td>
  </tr>
  <tr>
    <td>🤖 <b>Android Chrome</b></td>
    <td>Open the link → ⋮ menu → <b>Install app</b> (or <b>Add to Home screen</b>)</td>
  </tr>
  <tr>
    <td>💻 <b>Desktop Chrome / Edge</b></td>
    <td>Open the link → address-bar install icon (⊕ in the right side) → Install</td>
  </tr>
</table>

After install, the PWA launches full-screen like a native app. The
service worker caches the bundle so subsequent opens work without
network — only the day's feed JSON is fetched fresh.

---

## ✨ What it does

### 🗞️ Watches every source

Gmail newsletters, RSS feeds, and Twitter — all collected into one SQLite.
The feed list lives in [`config/`](config/). Add a source, restart the next
run, it shows up in the archive. No service to redeploy.

### 🔍 Four-tier dedup

Cross-channel duplicates collapse into clusters before summarization sees them
— exact URL → fuzzy text → simhash → semantic embedding. I only pay the LLM
once per story, not once per source. (And with a local model, even "paying
once" is near-free.)

### 🤖 Local-only AI by default

Provider is one env var (`AI_PROVIDER=ollama|anthropic|openai|gemini|minimax`).
Default is Ollama because it's free and runs locally. Swap to any
LiteLLM-supported provider with one row in
[`pipeline/AI/lm.py`](pipeline/AI/lm.py) — no other code changes.

### 📱 Static PWA frontend

A React/Vite PWA hosted on GitHub Pages reads JSON from the news-archive repo,
caches in IndexedDB, ranks by per-category preference with a 7-day decay.
Likes are weighted (reactions count half) so a viral story doesn't pollute
next week's feed.

---

## 🏗️ End-to-end pipeline

Each box is a real module under [`pipeline/`](pipeline/). Decision nodes
carry the actual thresholds used in code, not approximations.

```mermaid
flowchart TD
    subgraph SRC[Sources]
        S1[Gmail<br/>IMAP rolling window]
        S2[RSS<br/>HTTP fetch of configured feeds]
        S3[Twitter<br/>Playwright on configured handles]
    end

    SRC --> ING

    subgraph ING["Stage 1 · Ingest — pipeline/ingestion/"]
        I1[Fetch raw items]
        I2[URL canonicalize<br/>strip tracking params, unwrap redirects]
        I3{URL exists in items?}
        I3 -- yes --> I4[Skip]
        I3 -- no --> I5[Insert row as primary]
        I1 --> I2 --> I3
    end

    ING --> LINK

    subgraph LINK["Stage 2 · Relation linker — pipeline/relation/"]
        L1[Build embedding per news item]
        L2[For each tweet: nearest news by cosine]
        L3{Above similarity threshold?}
        L3 -- no --> L4[Standalone tweet]
        L3 -- yes --> L5{Tweet posted BEFORE matched news?}
        L5 -- yes --> L6[Scoop<br/>relation=standalone<br/>+ parent_cluster_id]
        L5 -- no --> L7[Reaction<br/>relation=reaction<br/>+ parent_cluster_id]
        L1 --> L2 --> L3
    end

    LINK --> DEDUP

    subgraph DEDUP["Stage 3 · Dedup T1–T4 — pipeline/dedup/"]
        D1{T1 exact URL or title?}
        D2{T2 fuzzy text + recent?}
        D3{T3 simhash near-match?}
        D4{T4 semantic embedding match?}
        D5[New singleton cluster]
        D6[Join existing cluster]
        D7[pick_primary<br/>official > aggregator > newsletter > unknown]
        D1 -- yes --> D6
        D1 -- no --> D2
        D2 -- yes --> D6
        D2 -- no --> D3
        D3 -- yes --> D6
        D3 -- no --> D4
        D4 -- yes --> D6
        D4 -- no --> D5
        D5 --> D7
        D6 --> D7
    end

    DEDUP --> SUM

    subgraph SUM["Stage 4 · Summarize — pipeline/AI/"]
        SM1[Pick primary items where summary IS NULL]
        SM2[Merge cluster content<br/>primary title + member bodies]
        SM3[DSPy ChainOfThought via configured provider]
        SM4[Emit key_facts + teaser + summary<br/>+ importance + category]
        SM5{Hot cluster?}
        SM5 -- yes --> SM6[Bump importance]
        SM5 -- no --> SM7[Importance unchanged]
        SM1 --> SM2 --> SM3 --> SM4 --> SM5
    end

    SUM --> EXP

    subgraph EXP["Stage 5 · Export — pipeline/git_export.py"]
        E1[Recent days from DB]
        E2[Write news-archive/&lt;Year&gt;/&lt;Month&gt;/&lt;dd-Mon-yy&gt;.json]
        E3[git add + commit + push]
        E1 --> E2 --> E3
    end

    EXP -- "git push HTTPS" --> ARC[(news-archive<br/>GitHub repo<br/>public, per-day JSON)]
```

The whole pipeline shares one SQLite at [`db/snapshot.db`](db/) and emits a
JSON envelope per stage so any agent / cron / skill can drive it. Detailed
stage docs live alongside the code:
[`pipeline/dedup/doc.md`](pipeline/dedup/doc.md),
[`pipeline/AI/doc.md`](pipeline/AI/doc.md),
[`pipeline/doc.md`](pipeline/doc.md).

---

## 🎨 The reader is intentionally lite

The frontend is a static bundle on GitHub Pages. It never talks to my
laptop — it only fetches per-day JSON files from `news-archive`, caches
them in the browser, and works offline once loaded. No backend, no
accounts, no server-side anything.

### Personalization stays on the device

Every like, every read, every swipe lives in the browser's local
storage. Nothing leaves the device. The ranking model is small enough
to explain in one paragraph:

- Each like contributes a weight toward the category and source it
  belongs to.
- Older likes decay smoothly, so a story that mattered last month
  doesn't permanently colour next week's feed.
- Reactions count at a lighter weight than primary news — a viral
  cluster with several reaction-likes shouldn't dominate the future
  feed as if they were independent signals.
- Total stored likes are capped; the oldest get evicted when new ones
  arrive, so the model can't grow unbounded.
- The final score for any unread item combines the AI's importance
  rating with the user's accumulated category and source preferences.

The result: a feed that re-orders itself around what someone actually
reads, without an account, without a recommendation server, without
their data ever leaving the browser tab.

---

## 🔌 Plugin skills

<table>
  <tbody>
    <tr>
      <td>🩺 <b>Inspection</b><br/><sub>auto-invocable, read-only</sub></td>
      <td><code>status</code> · <code>heal</code></td>
    </tr>
    <tr>
      <td>📥 <b>Ingest</b><br/><sub>user-only, writes DB</sub></td>
      <td><code>ingest-gmail</code> · <code>ingest-rss</code> · <code>ingest-twitter</code></td>
    </tr>
    <tr>
      <td>⚙️ <b>Process</b><br/><sub>user-only, writes DB</sub></td>
      <td><code>link-relations</code> · <code>dedup</code> · <code>summarize</code></td>
    </tr>
    <tr>
      <td>📤 <b>Publish</b><br/><sub>user-only, external side-effects</sub></td>
      <td><code>export</code> (git push) · <code>notify</code> (Telegram)</td>
    </tr>
    <tr>
      <td>🚀 <b>Run</b><br/><sub>chains all of the above</sub></td>
      <td><code>run</code> — parity with <code>uv run syndicate</code></td>
    </tr>
  </tbody>
</table>

Side-effect skills carry `disable-model-invocation: true`, so Claude won't
fire them by accident. You invoke them explicitly. See
[INSTALL.md](INSTALL.md) for the per-skill env requirements.

---

## ⚠️ Honest limitations

- **It's local.** Skills read your `.env`, write to local SQLite, and talk to
  Ollama on `localhost`. Claude Code reaches all of those. Claude's chat web
  app can't — that runtime is sandboxed off from your machine.
- **Twitter scraping is fragile.** Playwright + a persistent Chrome profile.
  When X.com changes its DOM, the selectors break and I update them. Skip
  Twitter if you don't want that maintenance.
- **Tuned for my reading.** Categories, importance heuristics, and the feed
  list reflect what I want to see. Easy to retune — see the category enum in
  [`pipeline/AI/`](pipeline/AI/).

---

## 🤝 Contributing

Issues and PRs welcome. Module-level docs live next to the code:
[`pipeline/*/doc.md`](pipeline/). Start there before editing — they describe
what each module is and isn't responsible for.

## 📝 License

[MIT](LICENSE). Copyright (c) 2026 Aadarsh Velu.
