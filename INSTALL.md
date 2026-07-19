# Installing the syndicate plugin

This document is the single source of truth for plugin installation. Each
SKILL.md does its own per-skill preflight (running `status` and checking
`env_present.<VAR>`), but the "how do I set this up at all" answer lives
here.

The syndicate plugin is a thin Claude-Code-facing skin over the pipeline
in this repo. It expects:

1. A working **syndicate checkout** (this repo, with `uv sync` done)
2. A **`.env` file at the repo root** holding the credentials the
   pipeline needs (see [`.env.example`](.env.example))
3. The `SYNDICATE_REPO` env var pointing at that checkout - required ONLY
   when the agent's cwd isn't the syndicate repo itself

The plugin contains no secrets and no per-machine state. All credentials
live in your local `.env`, which is gitignored.

---

## 1. Prerequisites

Same as running syndicate directly:

| Tool | Why | Install |
|---|---|---|
| Python 3.11+ | Pipeline runtime | system / pyenv |
| [`uv`](https://github.com/astral-sh/uv) | Lockfile + venv manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `git` | Used by `/syndicate-export` | system |
| One AI provider | Summarize + embeddings | Ollama (default) / Anthropic / OpenAI / Gemini / Minimax |
| Chrome + Playwright | `/syndicate-ingest-twitter` with default backend | `uv run install-browsers` |
| Hermes Tweet/Xquik API key | `/syndicate-ingest-twitter` with `TWITTER_BACKEND=hermes_tweet` | Create an API key in Xquik |

If you're only using a subset of channels (e.g. RSS-only), you can skip
the credentials for the channels you don't need - the corresponding
skills will refuse to start via their preflight check, but the rest of
the pipeline keeps working.

## 2. Install paths

### Option A - direct (you cloned this repo)

```bash
git clone https://github.com/aadarshvelu/syndicate.git
cd syndicate
uv sync
cp .env.example .env
$EDITOR .env                    # fill in the vars you need
```

`SYNDICATE_REPO` is not needed in this mode - the skill runs from inside
the repo and falls back to `$(pwd)`.

### Option B - Claude Code plugin install (other working dir)

Once you have a syndicate checkout, install the plugin from it:

```
/plugin marketplace add /path/to/syndicate
/plugin install syndicate-pipeline@syndicate
```

Then in your shell rc:

```bash
export SYNDICATE_REPO=/path/to/syndicate
```

The skill bodies all do `cd "${SYNDICATE_REPO:-$(pwd)}"` before invoking
`uv run python -m pipeline.cli`, so this var is what tells them where to
go. The `.env` they read lives inside `$SYNDICATE_REPO/.env` - there is
no separate plugin-side env file.

> **Note** - `/plugin marketplace add` currently expects the target dir
> to contain `.claude-plugin/marketplace.json`. If yours doesn't yet,
> see "Publishing" below.

## 3. The `.env` matrix

The full per-field documentation is in [`.env.example`](.env.example).
Quick reference of which var unlocks which skill:

| Variable | Required for | Notes |
|---|---|---|
| `SYNDICATE_REPO` | Plugin (Option B install) | Absolute path to the syndicate checkout |
| `GMAIL_USER` | `/syndicate-ingest-gmail` | IMAP login |
| `GMAIL_APP_PASSWORD` | `/syndicate-ingest-gmail` | Google App Password, not your account password |
| `AI_PROVIDER` | Summarize, dedup, link-relations | `ollama` (default) / `anthropic` / `openai` / `gemini` / `minimax` |
| `SUMMARIZE_MODEL` | Summarize | Provider-native name (no prefix). Has per-provider defaults |
| `EMBEDDING_MODEL` | Dedup, link-relations | Provider-native name. Has per-provider defaults |
| `EMBEDDING_PROVIDER` | Dedup, link-relations | Optional. Defaults to `AI_PROVIDER`. Set when `AI_PROVIDER` is `anthropic`/`minimax` (no embedding API). Supports `ollama`, `openai`, `gemini`, `voyage`, `cohere` |
| `OLLAMA_HOST` | Ollama provider | Default `http://localhost:11434` |
| `ANTHROPIC_API_KEY` | Anthropic provider | |
| `OPENAI_API_KEY` | OpenAI provider | |
| `GEMINI_API_KEY` | Gemini provider | Get one at https://aistudio.google.com/apikey |
| `MINIMAX_API_KEY` | Minimax provider | |
| `VOYAGE_API_KEY` | Voyage (embedding-only) | |
| `COHERE_API_KEY` | Cohere | |
| `FEED_REPO_URL` | `/syndicate-export` | HTTPS URL of news-archive repo |
| `FEED_REPO_PAT` | `/syndicate-export` | PAT with `contents: write` |
| `TWITTER_BACKEND` | `/syndicate-ingest-twitter` | Optional. `playwright` default, or `hermes_tweet` |
| `CHROME_EXECUTABLE` | `/syndicate-ingest-twitter` | Path to a Chrome/Chromium binary |
| `CHROME_PROFILE_DIR` | `/syndicate-ingest-twitter` | Persistent profile dir (cookies/session) |
| `TWITTER_HEADLESS` | `/syndicate-ingest-twitter` | Optional, default `true` |
| `XQUIK_API_KEY` | `/syndicate-ingest-twitter` with `TWITTER_BACKEND=hermes_tweet` | Hermes Tweet/Xquik API key |
| `XQUIK_BASE_URL` | `/syndicate-ingest-twitter` with `TWITTER_BACKEND=hermes_tweet` | Optional, defaults to `https://xquik.com/api/v1` |
| `TELEGRAM_BOT_TOKEN` | `/syndicate-notify`, auto-notify on `/syndicate-run` | From @BotFather |
| `TELEGRAM_CHAT_ID` | `/syndicate-notify`, auto-notify on `/syndicate-run` | Numeric, negative for groups |

The AI scheme is provider-agnostic: pick `AI_PROVIDER`, set the matching
API key (or `OLLAMA_HOST`), and optionally override `SUMMARIZE_MODEL` /
`EMBEDDING_MODEL` with a provider-native name. `pipeline/AI/lm.py`
constructs the LiteLLM-style `<prefix>/<model>` string for DSPy. Adding a
new LiteLLM-supported provider is one row in `_PROVIDERS` in that file.

`pipeline/cli.py` auto-loads `.env` on every subcommand invocation, so the
skill bodies do not have to worry about env loading.

## 4. How env loading actually works

For anyone reading the skill bodies and wondering where the credentials
come from:

1. Each SKILL.md invokes `uv run python -m pipeline.cli <subcommand>` via
   Bash. That's a fresh subprocess.
2. [`pipeline/cli.py:30-32`](pipeline/cli.py#L30-L32) calls
   `load_dotenv(_REPO/".env")` at import time, before any other pipeline
   module loads.
3. `_REPO` is computed from `Path(__file__).resolve().parents[1]`, so it
   always points at the actual installed repo - independent of `cwd` or
   `SYNDICATE_REPO`.
4. Shell-exported vars win over `.env` (standard `python-dotenv`
   behavior). Useful for overriding a single value without editing the
   file.

Implication: **Claude Code's own environment doesn't matter**. You don't
need to export GMAIL_USER in your shell or in the launchd plist - the
`.env` is the single source of truth, and the subprocess reads it
directly.

## 5. Preflight convention

Side-effect skills follow a uniform Step 1:

> Run `uv run python -m pipeline.cli status` and check
> `env_present.<VAR>` for the vars this skill needs. If any are `false`,
> stop with a clear message instead of attempting the operation.

This is implemented per-skill in each SKILL.md (search them for
"env_present"). When writing a new skill that needs creds, follow the
same pattern - there is no shared preamble file.

## 6. Verifying the install

```bash
cd "$SYNDICATE_REPO"
uv run python -m pipeline.cli status | jq '.result.env_present'
```

You should see a map of `{var: bool}`. Every var your selected channels
need should be `true`. Then dry-run a read-only skill:

```
/syndicate-status
```

It will print a one-line summary with per-channel counters. If you see
that, the install is working.

## 7. Publishing (push to GitHub, install via github source)

There is no "pack" step. The repo IS the plugin: `plugin.json` + `skills/`
sit at the root, and `marketplace.json` advertises the plugin via a
`github` source pointing back at this same repo:

```json
{
  "name": "syndicate",
  "owner": { "name": "Aadarsh velu", "email": "aadarshvelu@gmail.com" },
  "plugins": [
    {
      "name": "syndicate-pipeline",
      "source": { "source": "github", "repo": "aadarshvelu/syndicate" },
      "version": "0.1.0"
    }
  ]
}
```

Why github source instead of a relative path: Claude Code 2.1.x rejects
bare `"."` / `"./"` (the "source type your Claude Code version does not
support" error), and the canonical relative-path form requires the plugin
to be in a subdirectory. Using the `github` source skips both issues and
ships the same repo as both marketplace and plugin.

Push the repo, then any user can install with:

```
/plugin marketplace add aadarshvelu/syndicate
/plugin install syndicate-pipeline@syndicate
```

The skills do `cd "${SYNDICATE_REPO:-$(pwd)}"` to find the actual
pipeline code, so the cached plugin install location is irrelevant - it's
the env var that bridges plugin → pipeline.

Xquik is an independent third-party service. Not affiliated with X Corp. "Twitter" and "X" are trademarks of X Corp.
