# extractors

Maps a Gmail `From:` header to a stable `source_id` and an extractor
function. Used by [`pipeline/ingestion/gmail.py`](../ingestion/gmail.py) on
every fetched message.

The module is two things in one:

1. **Dispatcher** — `dispatch(from_header, sources)` resolves a sender to
   `(source_id, extractor_name)`.
2. **Extractor registry** — `EXTRACTORS` maps names to callables. Today
   only `"default"` is registered, pointing at
   [`pipeline/ingestion/extract_email.py:extract`](../ingestion/extract_email.py).

## Dispatch flow

```mermaid
flowchart TD
    A["dispatch(from_header, sources)"] --> B[Lowercase from_header]
    B --> C[Iterate sources from config/sources.json]
    C --> D{re.search src.match_from_pattern?}
    D -- yes --> E["return (src.id, src.extractor or 'default')"]
    D -- no --> F[Next source]
    F --> C
    C -- end of list --> G["_source_id_from_from(from_header)"]
    G --> H["parseaddr → local + domain"]
    H --> I{local in _GENERIC_LOCALS?<br/>noreply, hello, info, ...}
    I -- yes --> J[Use 2nd-level domain<br/>strip mail./email./newsletter./mg-./reply./send. prefix]
    I -- no --> K[Use local part]
    J --> L[Slug-ify: [^a-z0-9]+ → _, truncate 40 chars]
    K --> L
    L --> M["return (slug, 'default')"]
```

## Why fall back to a derived ID

Earlier versions returned `"unknown"` when no pattern matched, which
collapsed every unconfigured sender into a single bucket. The current
fallback keeps senders distinct so the dedup pipeline can attribute
items correctly even before you've added a `config/sources.json` entry.

Examples (real outputs):

| `From:` header | Resolved `source_id` |
|---|---|
| `"Stratechery <newsletter@stratechery.com>"` | `stratechery` (matched via config) |
| `"Casey Newton" <casey@platformer.news>"` | `casey` (local part, not generic) |
| `"Updates" <updates@mail.example.org>"` | `example` (local generic → 2nd-level domain) |

## Configured sources

`config/sources.json` is the override table. Each entry:

```json
{
  "id": "stratechery",
  "display_name": "Stratechery",
  "match_from_pattern": "stratechery\\.com",
  "extractor": "default"
}
```

The `match_from_pattern` is a Python regex run case-insensitively
against the full lowercased `From:` header. First match wins.

## Adding a custom extractor

```python
# in pipeline/extractors/__init__.py
def _stratechery_extract(html_payload: str, ...) -> dict:
    ...

EXTRACTORS["stratechery"] = _stratechery_extract
```

Then point the config entry at it:

```json
{ "id": "stratechery", "match_from_pattern": "...", "extractor": "stratechery" }
```

`get_extractor(name)` resolves the function; unknown names fall back to
`extract` (the default readability+strip-pixels cleaner).

## Module boundaries

- The default extractor lives in `pipeline/ingestion/extract_email.py`,
  not here, because it's tightly coupled to the IMAP HTML payload
  shape. This module is just the dispatch table.
- Per-source custom extractors should live here in
  `pipeline/extractors/__init__.py` (or a sibling file) and be
  registered in `EXTRACTORS`.
