# AI

LLM enrichment — generates teaser, summary, importance, and category for each primary item.

## Flow

```mermaid
flowchart TD
    A["SummarizePipeline.run()"] --> B["items_needing_summary — is_primary=1 AND summary IS NULL"]
    B --> C["for_llm() — strip HTML, truncate to 8K"]
    C --> D["cluster_members_content() — up to 2 member bodies"]
    D --> E["_build_content() — merge + truncate proportionally"]
    E --> F["_build_prompt() — JSON field instructions + category enum"]
    F --> G["_ollama_chat() — POST /api/chat, format=schema, think=False"]
    G --> H["strip markdown fences if model wraps output"]
    H --> I["ItemSummary.model_validate() — Pydantic validation"]
    I --> J{cluster_size >= 3?}
    J -->|yes| K["importance = min(5, importance + 1)"]
    J -->|no| L["importance unchanged"]
    K --> M["set_enrichment() — write teaser, summary, importance, category"]
    L --> M
    M --> N["commit every 10 items"]
```

## Why `key_facts` is first in the schema

The model must enumerate up to 8 verbatim facts (names, numbers, dates, key claims) before writing prose. This acts as a chain-of-thought anchor — grounding the teaser and summary in extracted facts rather than hallucinated ones. Every fact from `key_facts` must appear in the summary.

## Output schema

| Field | Constraint | Purpose |
|-------|-----------|---------|
| `key_facts` | list[str], max 8 | CoT grounding step |
| `teaser` | ≤150 chars | Hook shown on card face in PWA |
| `summary` | ≤450 chars | Full story, inverted pyramid |
| `importance` | int 1–5 | 5 = major breaking news, 1 = routine |
| `category` | enum | Filter/browse in PWA |

## Categories

`ai_research` · `ai_products` · `economics` · `policy` · `startup` · `world_news` · `tech_news` · `other`

## Model

Default: `gemma4:latest`. Override via `OLLAMA_SUMMARIZE_MODEL` env var or `--model` flag.
Server: `OLLAMA_URL` (default `http://localhost:11434`).

## Entrypoint

```bash
uv run python -m pipeline.AI.summarize_pipeline --limit 50
uv run python -m pipeline.AI.summarize_pipeline --limit 5 --model qwen3.5:9b
```
