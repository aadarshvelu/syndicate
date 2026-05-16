---
name: syndicate-dedup
description: Run the T1–T4 dedup pipeline to cluster near-duplicate items across the rolling window.
when_to_use: |
  When the user asks to "run dedup", "cluster items", "merge duplicates",
  or after ingesting new content that should join existing clusters.
argument-hint: "[--window-days 10] [--tiers 1,2,3,4]"
arguments:
  - name: window_days
    type: int
    required: false
disable-model-invocation: true
allowed-tools:
  - Bash(uv run python -m pipeline.cli dedup*)
  - Bash(cd:*)
context: fork
---

# /syndicate-dedup

You are running dedup. **Writes to the DB** — sets `cluster_id`,
`is_primary`, and `cluster_method`. Idempotent.

## Step 1 — run dedup

Defaults: window=10 days, tiers=1,2,3,4 (T1 exact URL, T2 fuzzy title,
T3 simhash, T4 semantic embedding). Parse `$ARGUMENTS` for overrides:

    cd "${SYNDICATE_REPO:-$(pwd)}" && uv run python -m pipeline.cli dedup --window ${window_days:-10} --tiers ${tiers:-1,2,3,4}

Output envelope:

```json
{"ok": true, "result": {"examined": N, "new_clusters": N, "items_demoted": N, "matched_phase1": N, "matched_phase2": N, "method_counts": {"singleton": N, "t1_exact": N, "t2_fuzzy": N, "t3_simhash": N, "t4_semantic": N}, "errors": []}, "log_path": "..."}
```

## Step 2 — report

    ✓ dedup · examined=X clusters=Y demoted=Z [singleton=A t4_semantic=B ...]

`items_demoted` is the count of rows that lost `is_primary=1` because a
better representative was chosen for their cluster. Demoted items are
excluded from the FE feed but kept in the DB for reaction-graph integrity.
