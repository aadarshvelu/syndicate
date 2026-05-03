# pipeline

Top-level orchestrator and shared core modules.

## Orchestration flow

```mermaid
flowchart TD
    CLI["digest CLI — pipeline/main.py"]

    CLI --> G_SKIP{--skip-gmail?}
    G_SKIP -->|no| GMAIL["GmailPipeline"]
    G_SKIP -->|yes| R_SKIP

    GMAIL --> R_SKIP{--skip-rss?}
    R_SKIP -->|no| RSS["RssPipeline"]
    R_SKIP -->|yes| D_SKIP

    RSS --> D_SKIP{--skip-dedup?}
    D_SKIP -->|no| DEDUP["DedupPipeline"]
    D_SKIP -->|yes| S_SKIP

    DEDUP --> S_SKIP{--skip-summarize?}
    S_SKIP -->|no| SUM["SummarizePipeline"]
    S_SKIP -->|yes| OUT

    SUM --> OUT["DigestResult JSON → stdout"]
```

Each stage writes to SQLite (`storage.py`) independently. A failed stage is logged and skipped — subsequent stages still run against whatever is already in the DB.

## Shared core

| File | Role |
|------|------|
| `storage.py` | SQLite `ItemStore` — all DB reads/writes go through here |
| `clean.py` | HTML→plain-text: `to_text`, `for_embed`, `for_llm` |

## Subpackages

| Package | Purpose |
|---------|---------|
| `ingestion/` | Pull content from Gmail and RSS, normalize to unified schema |
| `dedup/` | Four-tier duplicate detection and cluster assignment |
| `AI/` | LLM enrichment — teaser, summary, importance, category |
| `auth/` | Gmail IMAP authentication |
| `extractors/` | Map email From: headers to `source_id` |
| `tools/` | Dev/debug scripts — simulate, smoke tests |
