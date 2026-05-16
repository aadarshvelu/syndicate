---
name: syndicate-export
description: Export today's + last 3 days of digest items to the news-archive repo and push. External side-effect (git push).
when_to_use: |
  When the user explicitly asks to "export", "publish to news-archive",
  "push the feed", or after a successful summarize run when they want
  the items visible in the PWA.
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli export*)
  - Bash(uv run python -m pipeline.cli status*)
  - Bash(cd:*)
context: inline
---

# /syndicate-export

You are exporting the digest to the news-archive git repo and pushing it
remotely. **External side-effect** — only run when the user explicitly asked.

## Step 1 — preflight
Run `status` and confirm:

- `env_present.FEED_REPO_URL` is `true`
- `env_present.FEED_REPO_PAT` is `true`

If either is missing, tell the user which one and stop. The export will
fail at the `git push` step otherwise, but the items will already have
been written to the local news-archive working tree, leaving them in a
half-committed state.

## Step 2 — export
Run:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli export

Output envelope:

```json
{"ok": true, "result": {"exported_today": N, "exported_yesterday": N, "committed": true, "pushed": true, "errors": []}, "log_path": "..."}
```

## Step 3 — report
One line:

    ✓ export · today=+X yesterday=+Y · committed · pushed

`exported_today` and `exported_yesterday` only count the most recent two
days for backwards compatibility — but the underlying export now writes
the last 4 days as a window (so post-outage catch-up doesn't drop items
on the floor). If both are 0 and `committed=false`, the run was a no-op
because all items in the window are already in the remote repo.

If `pushed=false` but `committed=true`, the local repo got the commit
but `git push origin main` failed (auth, network, or remote ahead). The
user can usually fix by running `git -C <news-archive-path> push` manually.
