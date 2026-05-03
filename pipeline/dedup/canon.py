"""URL and title normalization helpers for dedup tier 1.

URL canonicalization:
  - lowercase host, strip default ports
  - strip tracking query params (utm_*, fbclid, gclid, mc_eid, mc_cid, ...)
  - strip fragment
  - unwrap common wrapper / redirect URLs (Substack app-link, mailchimp,
    sendgrid, etc.) when the wrapper exposes the real URL as a query param

Title normalization:
  - lowercase, NFKC, strip emoji/non-letter symbols, collapse whitespace
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

# Tracking parameter prefixes / exact names to drop.
_TRACKING_EXACT = {
    "fbclid", "gclid", "msclkid", "yclid", "twclid",
    "mc_cid", "mc_eid",
    "ref", "ref_src", "ref_url",
    "share", "shared", "src",
    "wt_zmc", "wt_mc",
    "spm",
    "from", "campaign_id",
    "_hsenc", "_hsmi", "hsCtaTracking",
    "isFreemail", "publication_id", "post_id", "token",
}
_TRACKING_PREFIXES = ("utm_",)


# Substack "app-link" wrappers carry the real post path. We try to replace the
# wrapped URL with the publication's canonical post URL when possible.
_SUBSTACK_WRAPPER_RE = re.compile(r"^https?://substack\.com/app-link/post", re.I)


def _is_tracking(name: str) -> bool:
    n = name.lower()
    if n in _TRACKING_EXACT:
        return True
    return any(n.startswith(p) for p in _TRACKING_PREFIXES)


def _strip_tracking_params(query: str) -> str:
    if not query:
        return ""
    pairs = [
        (k, v) for (k, v) in parse_qsl(query, keep_blank_values=True)
        if not _is_tracking(k)
    ]
    return urlencode(pairs)


def _unwrap_substack(parsed) -> str | None:
    """If parsed URL is a substack.com/app-link, try to recover canonical."""
    if not _SUBSTACK_WRAPPER_RE.match(f"{parsed.scheme}://{parsed.netloc}{parsed.path}"):
        return None
    qs = parse_qs(parsed.query)
    # Substack puts publication_id + post_id; lacking the slug we can't
    # build the canonical post URL deterministically. Best we can do is
    # collapse to a stable key based on (publication_id, post_id).
    pub = (qs.get("publication_id") or [""])[0]
    post = (qs.get("post_id") or [""])[0]
    if pub and post:
        return f"https://substack-canon/{pub}/{post}"
    return None


def canonicalize_url(url: str) -> str:
    """Return a stable canonical form of the URL for tier-1 dedup.

    Returns "" for empty input. Does not perform network resolution.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    if not parsed.scheme or not parsed.netloc:
        return url

    canon = _unwrap_substack(parsed)
    if canon:
        return canon

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Strip default ports
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    # Strip leading "www."
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path or "/"
    # Drop trailing slash for non-root paths
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Decode %XX sequences in path conservatively
    try:
        path = unquote(path)
    except Exception:
        pass

    query = _strip_tracking_params(parsed.query)
    fragment = ""

    return urlunparse((scheme, netloc, path, "", query, fragment))


_TITLE_DROP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_title(title: str) -> str:
    """Aggressive normalization for tier-1 exact-title dedup.

    - NFKC unicode normalize
    - lowercase
    - replace any non-alphanumeric run with a single space
    - strip leading/trailing whitespace
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = t.lower()
    t = _TITLE_DROP_RE.sub(" ", t)
    return t.strip()
