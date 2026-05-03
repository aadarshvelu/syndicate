# dedup

Four-tier duplicate detection. Groups items into clusters and marks one per cluster as `is_primary=1`.

## Flow

```mermaid
flowchart TD
    A["DedupPipeline.run()"] --> B["items_in_window(days) — storage.py"]
    B --> C["Pre-compute SimHashes — simhash.py"]
    C --> D["Pre-compute embeddings — semantic.py"]

    D --> P1["PHASE 1: cluster unclustered items against each other"]

    P1 --> T1{T1: exact URL or title match?}
    T1 -->|yes| MATCH["Join existing cluster"]
    T1 -->|no| T2{T2: token_set_ratio >= 88 AND date within 24h?}
    T2 -->|yes| MATCH
    T2 -->|no| T3{T3: SimHash Hamming distance <= 3?}
    T3 -->|yes| MATCH
    T3 -->|no| T4{T4: cosine similarity >= 0.60?}
    T4 -->|yes| MATCH
    T4 -->|no| NEW["New singleton cluster"]

    MATCH --> P2
    NEW --> P2

    P2["PHASE 2: merge fresh singletons into pre-existing clusters"]

    P2 --> PERSIST["pick_primary() — priority.py"]
    PERSIST --> DB["assign_cluster() — is_primary 1 or 0"]
```

## Two-phase design

**Phase 1** only clusters items that don't yet have a `cluster_id` against each other. Items already in a cluster from previous runs are untouched.

**Phase 2** catches the case where a fresh item should belong to a *pre-existing* cluster from an earlier run — e.g., a newsletter covering a story that was already seen in RSS the day before.

## Tier modules

| File | Role |
|------|------|
| `runner.py` | `DedupPipeline` — orchestrates all tiers + both phases |
| `canon.py` | URL canonicalization (strip tracking params, unwrap wrappers); title normalization |
| `priority.py` | `pick_primary` — official > aggregator > newsletter > unknown; tie-break on content length then date |
| `simhash.py` | 64-bit 3-gram SimHash fingerprint; Hamming distance |
| `semantic.py` | Ollama embedding via HTTP; cosine on L2-normalized vectors; blob serialize/deserialize |

## Cluster method labels

Most-specific method label wins when multiple tiers could describe a cluster:

```
singleton → preexisting → t4_semantic → t3_simhash → t2_fuzzy → t1_exact
```
