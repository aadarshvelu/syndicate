---
name: syndicate-notify
description: Post a run summary to Telegram. External side-effect (sends a message to the configured chat).
when_to_use: |
  When the user explicitly asks to "send the run summary to Telegram",
  "notify Telegram", or "post the digest stats". Usually invoked manually
  to re-send a missed summary; the orchestrator run already auto-notifies.
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli notify*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
  - Read
context: inline
---

# /syndicate-notify

You are sending a Telegram message. **External side-effect** — only run
when the user explicitly asked.

## Step 1 — preflight
Run `status` and confirm `env_present.TELEGRAM_BOT_TOKEN` and
`env_present.TELEGRAM_CHAT_ID` are both `true`. If not, point the user at
the [bot setup](https://core.telegram.org/bots#how-do-i-create-a-bot) docs
and stop.

## Step 2 — send
The notify subcommand reads an OrchestratorResult JSON from stdin. If the
user has a recent `cli run` output handy (e.g. from a prior session log
or a file they pass), pipe it in:

    cd "${SYNDICATE_REPO:-$(pwd)}" && cat path/to/run-result.json | uv run python -m pipeline.cli notify

If the user just wants to re-send the LAST run summary without a stored
JSON, ask them to run `/syndicate-run` instead — that path notifies
automatically and is the canonical way to refresh the Telegram feed.

Output envelope:

```json
{"ok": true, "result": {"ok": true}, "log_path": null}
```

## Step 3 — report
One line: `✓ telegram notified` on success, otherwise show the error.
