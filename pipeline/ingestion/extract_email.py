from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from readability import Document


@dataclass
class ExtractedEmail:
    title: str
    url: str
    html: str
    text: str
    published_at: str
    author: str


TRACKING_FRAGMENTS = (
    "track.",
    "click.",
    "mailtrack",
    "list-manage.com",
    "mailchimp.com",
    "sendgrid.net",
    "substack.com/redirect",
    "stspg-customer",
    "sg-mta",
    "amazonses.com",
    "convertkit-mail",
    "beehiiv.com/click",
)

UNSUB_RE = re.compile(r"unsubscribe|view\s+in\s+browser|email\s+preferences", re.I)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_tracking(soup: BeautifulSoup) -> None:
    for img in soup.find_all("img"):
        src = (img.get("src") or "").lower()
        w = str(img.get("width") or "").strip()
        h = str(img.get("height") or "").strip()
        if not src or w in {"1", "0"} or h in {"1", "0"}:
            img.decompose()
            continue
        if any(t in src for t in TRACKING_FRAGMENTS):
            img.decompose()


def _strip_unsub_blocks(soup: BeautifulSoup) -> None:
    # Snapshot first — decomposing mid-iteration detaches descendants and
    # bs4's lazy iterator raises on stale handles.
    for node in list(soup.find_all(string=UNSUB_RE)):
        if getattr(node, "parent", None) is None:
            continue
        try:
            parent = node.find_parent(["table", "div", "tr", "td", "p", "section"])
        except AttributeError:
            continue
        if parent is not None and getattr(parent, "parent", None) is not None:
            parent.decompose()
    for hidden in list(soup.select("[style*='display:none'], [style*='display: none']")):
        if getattr(hidden, "parent", None) is None:
            continue
        hidden.decompose()


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    _strip_tracking(soup)
    _strip_unsub_blocks(soup)
    return str(soup)


def first_link(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lower = href.lower()
        if not href_lower.startswith("http"):
            continue
        if any(t in href_lower for t in TRACKING_FRAGMENTS):
            continue
        if "unsubscribe" in href_lower or "preferences" in href_lower:
            continue
        return href
    return ""


def parse_date(date_header: str) -> str:
    if not date_header:
        return _now_iso()
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return _now_iso()


def parse_author(from_header: str) -> str:
    if not from_header:
        return ""
    m = re.match(r'^"?([^"<]+?)"?\s*<', from_header)
    if m:
        return m.group(1).strip()
    return from_header.strip()


def extract(
    raw_html: str,
    raw_text: str,
    subject: str,
    from_header: str,
    date_header: str,
) -> ExtractedEmail:
    cleaned = clean_html(raw_html) if raw_html else ""
    title = (subject or "").strip()
    url = ""
    text = raw_text or ""

    if cleaned:
        try:
            doc = Document(cleaned)
            doc_title = (doc.short_title() or "").strip()
            # Subject wins — readability's short_title latches onto mastheads
            # like "TLDR Dev" which are identical across issues and break dedup.
            if not title and doc_title:
                title = doc_title
            article_html = doc.summary(html_partial=True)
            text = BeautifulSoup(article_html, "lxml").get_text(" ", strip=True)
            url = first_link(article_html) or first_link(cleaned)
        except Exception:
            text = BeautifulSoup(cleaned, "lxml").get_text(" ", strip=True)
            url = first_link(cleaned)

    return ExtractedEmail(
        title=title,
        url=url,
        html=cleaned,
        text=text,
        published_at=parse_date(date_header),
        author=parse_author(from_header),
    )
