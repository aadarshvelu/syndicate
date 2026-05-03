"""HTML → flat plain text cleaning.

Single shared module for all content consumers (embedding, LLM, display).
No new dependencies — uses readability-lxml, beautifulsoup4, lxml already
in pyproject.toml.

Public API:
  to_text(content, is_html)          -> str   core cleaner
  for_embed(content, is_html, title) -> str   truncated for embedding
  for_llm(content, is_html)          -> str   truncated for LLM
"""

from __future__ import annotations

import html
import re

READABILITY_THRESHOLD = 500   # min raw HTML chars before trying readability
EMBED_MAX_CHARS = 4000
LLM_MAX_CHARS = 8000

_NOISE_TAGS = {
    "script", "style", "head", "nav", "footer",
    "aside", "form", "iframe", "noscript", "svg",
}

_BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "td", "th", "dd", "dt",
    "div", "section", "article",
}

# Typographic normalisation map: fancy → ASCII
_TYPO_TABLE = str.maketrans({
    "‘": "'", "’": "'",   # left/right single quotes
    "“": '"', "”": '"',   # left/right double quotes
    "–": "-", "—": "-",   # en-dash, em-dash
    "…": "...",                 # ellipsis
    " ": " ",                   # non-breaking space
    "​": "",                    # zero-width space
})

_MULTI_NEWLINE = re.compile(r"\n{3,}")
_MULTI_SPACE   = re.compile(r"[ \t]{2,}")


def _normalise(text: str) -> str:
    text = html.unescape(text)
    text = text.translate(_TYPO_TABLE)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _bs4_walk(soup) -> str:
    """Walk block-level tags and join their text with newlines."""
    parts: list[str] = []
    for tag in soup.find_all(_BLOCK_TAGS):
        # Skip if a parent is also a block tag we've already captured.
        if tag.find_parent(_BLOCK_TAGS):
            continue
        chunk = tag.get_text(" ", strip=True)
        if chunk:
            parts.append(chunk)
    return "\n".join(parts) if parts else soup.get_text(" ", strip=True)


def to_text(content: str, is_html: bool = True) -> str:
    """Convert HTML or plain-text content to clean flat plain text."""
    if not content:
        return ""

    if not is_html:
        return _normalise(content)

    # ── HTML path ────────────────────────────────────────────────────────────
    from bs4 import BeautifulSoup

    # 1. Strip noise tags before any parsing
    soup = BeautifulSoup(content, "lxml")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)):
        tag.decompose()
    for tag in soup.find_all(hidden=True):
        tag.decompose()

    cleaned_html = str(soup)

    # 2. Try readability for article-length content
    text = ""
    if len(cleaned_html) >= READABILITY_THRESHOLD:
        try:
            from readability import Document
            doc = Document(cleaned_html)
            summary_html = doc.summary(html_partial=True)
            if summary_html:
                inner = BeautifulSoup(summary_html, "lxml")
                text = _bs4_walk(inner)
        except Exception:
            pass

    # 3. BS4 structured walk fallback
    if not text:
        text = _bs4_walk(soup)

    return _normalise(text)


def for_embed(content: str, is_html: bool = True, title: str = "") -> str:
    """Clean text for embedding. Prepends title, truncates to EMBED_MAX_CHARS."""
    text = to_text(content, is_html)
    title = (title or "").strip()
    combined = f"{title}\n\n{text}" if title and text else (title or text)
    return combined[:EMBED_MAX_CHARS]


def for_llm(content: str, is_html: bool = True, max_chars: int = LLM_MAX_CHARS) -> str:
    """Clean text for LLM summarisation. Truncates to max_chars."""
    return to_text(content, is_html)[:max_chars]
