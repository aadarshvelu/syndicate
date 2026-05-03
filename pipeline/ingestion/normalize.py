from __future__ import annotations

from pipeline.clean import to_text
from pipeline.ingestion.extract_email import ExtractedEmail
from pipeline.ingestion.fetch import FetchResult
from pipeline.storage import (
    dedup_key_for_msg,
    dedup_key_for_url,
    new_id,
    now_iso,
)


def gmail_to_item(
    extracted: ExtractedEmail,
    source_id: str,
    message_id: str,
    raw_meta: dict | None = None,
) -> dict:
    has_html = bool(extracted.html and extracted.html.strip())
    raw_content = extracted.html if has_html else (extracted.text or "")
    content = to_text(raw_content, is_html=has_html)
    is_html = False

    if extracted.url:
        dk = dedup_key_for_url(extracted.url)
    else:
        dk = dedup_key_for_msg(message_id, extracted.title)

    meta = {"gmail_message_id": message_id}
    if raw_meta:
        meta.update(raw_meta)

    return {
        "id": new_id(),
        "dedup_key": dk,
        "source_id": source_id,
        "source_channel": "gmail",
        "title": extracted.title,
        "desp": "",
        "date": extracted.published_at,
        "content": content,
        "is_html": is_html,
        "url": extracted.url,
        "author": extracted.author,
        "fetched_at": now_iso(),
        "raw_meta": meta,
    }


def rss_to_item(
    entry: dict,
    fetch: FetchResult | None,
    source: dict,
) -> dict | None:
    title = (entry.get("title") or "").strip()
    url = entry.get("link") or ""
    teaser = entry.get("summary") or ""

    if fetch and fetch.ok and (fetch.content_html or fetch.content_text):
        raw_content = fetch.content_html or fetch.content_text
        content = to_text(raw_content, is_html=bool(fetch.content_html))
    elif teaser:
        content = to_text(teaser, is_html=True)
    else:
        return None
    is_html = False
    teaser = to_text(teaser, is_html=True) if teaser else ""

    dt = entry.get("published_at")
    date_iso = dt.isoformat().replace("+00:00", "Z") if dt else ""

    raw_meta = {
        "rss_entry_id": entry.get("id"),
        "rss_tags": entry.get("tags") or [],
        "fetch_ok": bool(fetch and fetch.ok) if fetch else None,
        "fetch_status": fetch.status if fetch else None,
        "fetch_error": fetch.error if (fetch and not fetch.ok) else None,
    }

    if url:
        dk = dedup_key_for_url(url)
    else:
        dk = dedup_key_for_msg(source.get("id", ""), title)

    return {
        "id": new_id(),
        "dedup_key": dk,
        "source_id": source.get("id", ""),
        "source_channel": "rss",
        "title": title,
        "desp": teaser if teaser != content else "",
        "date": date_iso,
        "content": content,
        "is_html": is_html,
        "url": url,
        "author": entry.get("author") or "",
        "fetched_at": now_iso(),
        "raw_meta": raw_meta,
        "image_url": fetch.image_url if fetch and fetch.ok else "",
    }
