---
name: syndicate-summarize
description: Run the AI summarizer over up to LIMIT unsummarized items. Writes teaser/summary/importance/category to DB.
when_to_use: |
  When the user asks to "summarize", "run summarize", "process the
  unsummarized backlog", or after ingestion when they want to advance to
  enrichment.
argument-hint: "[--limit 50]"
arguments:
  - name: limit
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli summarize*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: fork
---

# /syndicate-summarize

You are running the AI summarizer. This **writes summary fields to the DB**
and **calls an LM** (whichever provider `AI_PROVIDER` selects: `ollama`,
`anthropic`, `openai`, `gemini`, `minimax`). Cost-bearing — only run when
the user explicitly asked.

## Step 1 — preflight
Run `status` and verify the provider matching `env_present.AI_PROVIDER`
(default `ollama` when unset) has its credential:

- `ollama`    → `ollama_reachable` is `true`
- `anthropic` → `env_present.ANTHROPIC_API_KEY` is `true`
- `openai`    → `env_present.OPENAI_API_KEY` is `true`
- `gemini`    → `env_present.GEMINI_API_KEY` is `true`
- `minimax`   → `env_present.MINIMAX_API_KEY` is `true`

If the provider can't be reached or the required key is missing, stop with
a clear error rather than burning items on transient failures.

Also report `items_unsummarized` from status — that's the upper bound on
what this run could process.

## Step 2 — summarize
Default `--limit` is 50. Parse `$ARGUMENTS` for `--limit N`:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli summarize --limit ${limit:-50}

Each item takes ~1–18 minutes depending on provider/model and whether the
item has an image (vision items are slower). For local Ollama on a Mac
M-series, plan ~2 minutes per item on average. The skill runs in a forked
subagent context so progress logs are isolated.

Output envelope:

```json
{"ok": true, "result": {"examined": N, "summarized": N, "skipped": N, "errors": []}, "log_path": "..."}
```

## Step 3 — report

    ✓ summarize · examined=X done=Y skipped=Z

`skipped` includes items the summarizer classified as `banter`,
`empty_content`, or `reaction` (which have a `skip_reason` persisted so
they never re-process). Surface unexpected `errors[]` entries verbatim —
those are transient failures and will retry on the next run.
