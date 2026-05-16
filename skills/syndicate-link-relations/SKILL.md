---
name: syndicate-link-relations
description: Run the syndicate relation linker — finds reaction/standalone links between tweets and news clusters.
when_to_use: |
  When the user asks to "link relations", "rerun the linker", "find missing
  tweet→news links", or after manually ingesting new tweets that should
  attach to existing news clusters.
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli link*)
  - Bash(cd:*)
context: inline
---

# /syndicate-link-relations

You are running the relation linker. It examines unlinked items, computes
semantic similarity against the active news clusters, and assigns each item
either `relation = standalone` or `relation = reaction` with a
`parent_cluster_id`. **Writes to the DB** (relation/parent fields only).

## Step 1 — run the linker

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli link

Output envelope:

```json
{"ok": true, "result": {"examined": N, "standalone": N, "reactions": N, "errors": []}, "log_path": "logs/<date>.txt"}
```

## Step 2 — report
One line:

    ✓ link · examined=X standalone=Y reactions=Z

Note: the linker is idempotent — running it twice in a row is safe and
the second pass should report `examined=0` (or close to it) because the
first pass marked everything.
