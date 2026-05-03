# ingestion

Pulls content from Gmail and RSS, normalizes everything to the unified item schema, persists to SQLite.

## Gmail flow

```mermaid
flowchart TD
    A["GmailPipeline.run()"] --> B["IMAP session — auth/gmail.py"]
    B --> C["select_label — imap.py"]
    C --> D["search_uids SINCE date"]
    D --> E["fetch_message per UID"]
    E --> F["extract_html_payload"]
    F --> G["extract() — strip tracking pixels, readability parse"]
    G --> H["dispatch() — map From: to source_id"]
    H --> I["gmail_to_item() — normalize to item dict"]
    I --> J["ItemStore.insert_items()"]
```

**Pre-filter:** Empty payloads (no title and no text) are dropped before DB insert.

## RSS flow

```mermaid
flowchart TD
    A["RssPipeline.run()"] --> B["fetch_all() in parallel — feedparser + httpx"]
    B --> C["Filter by published_at >= window_since(days)"]
    C --> D["existing_dedup_keys() — skip already-stored"]
    D --> E{fetch_full flag?}
    E -->|yes| F["fetch_urls() — readability + OG image"]
    E -->|no| G["use RSS entry summary as content"]
    F --> H["rss_to_item() — normalize to item dict"]
    G --> H
    H --> I["ItemStore.insert_items()"]
```

**Pre-filter:** Items with no content and no summary are dropped (`rss_to_item` returns `None`).

## Modules

| File | Role |
|------|------|
| `gmail.py` | `GmailPipeline` — IMAP ingestion runner |
| `rss.py` | `RssPipeline` — RSS ingestion runner |
| `imap.py` | Low-level IMAP ops: select, search, fetch, decode headers |
| `feeds.py` | Async RSS fetch via feedparser + httpx; date windowing |
| `fetch.py` | Async per-URL article fetcher; readability extraction; OG image |
| `normalize.py` | `gmail_to_item`, `rss_to_item` → unified item dict |
| `extract_email.py` | Email HTML cleaner: tracking pixel strip, unsub block removal, readability |
| `sources.py` | Load Gmail source registry from `config/sources.json` |

## Unified item schema

```
id              UUIDv4
dedup_key       SHA1(url) or SHA1(msgid|title)
source_id       stable identifier for the sender/feed
source_channel  "gmail" | "rss"
title           article/email subject
desp            RSS teaser (empty for Gmail)
date            published ISO8601 UTC
content         pre-cleaned plain text (is_html=0 on all new rows)
url             canonical article URL
author          sender display name or byline
fetched_at      pipeline run time ISO8601 UTC
raw_meta        JSON blob of channel-specific metadata
image_url       OG/Twitter card image (RSS only)
```
