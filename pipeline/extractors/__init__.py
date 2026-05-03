from __future__ import annotations

import re
from collections.abc import Callable
from email.utils import parseaddr

from pipeline.ingestion.extract_email import extract

# Local parts that identify the ESP/platform, not the publication.
_GENERIC_LOCALS = frozenset({
    "newsletter", "noreply", "no-reply", "reply", "hello",
    "info", "contact", "mail", "email", "news", "updates",
    "notifications", "support", "team", "hi", "hey",
})

# Subdomain prefixes that add no identity signal.
_STRIP_SUBDOMAIN = re.compile(
    r"^(?:mail|email|newsletter|news|mg[\w-]*|reply|updates|send)\.",
    re.I,
)


def _source_id_from_from(from_header: str) -> str:
    """Derive a stable source_id from a From header with no pattern match.

    Priority: meaningful local part > second-level domain > display name.
    Never returns 'unknown' unless the header is completely empty.
    """
    _, addr = parseaddr(from_header)
    addr = addr.lower().strip()

    if addr and "@" in addr:
        local, domain = addr.split("@", 1)
        local = local.split("+")[0]                     # strip +suffix
        domain = _STRIP_SUBDOMAIN.sub("", domain)       # strip ESP subdomain prefixes
        if local not in _GENERIC_LOCALS:
            candidate = local
        else:
            # Fall back to second-level domain (e.g. stratechery from stratechery.com)
            parts = domain.split(".")
            candidate = parts[-2] if len(parts) >= 2 else parts[0]
    else:
        # No parseable address — use display name
        display = re.sub(r"<.*?>", "", from_header).strip().lower()
        candidate = display or "unknown"

    return re.sub(r"[^a-z0-9]+", "_", candidate).strip("_")[:40] or "unknown"


def dispatch(from_header: str, sources: list[dict]) -> tuple[str, str]:
    """Map a From: header to (source_id, extractor_name).

    Falls back to a domain-derived source_id instead of 'unknown' so every
    Gmail item has a stable, meaningful identifier even for unconfigured senders.
    """
    from_lower = from_header.lower()
    for src in sources:
        pattern = src.get("match_from_pattern")
        if pattern and re.search(pattern, from_lower, re.I):
            return src["id"], src.get("extractor", "default")
    return _source_id_from_from(from_header), "default"


EXTRACTORS: dict[str, Callable] = {
    "default": extract,
}


def get_extractor(name: str) -> Callable:
    return EXTRACTORS.get(name, extract)
