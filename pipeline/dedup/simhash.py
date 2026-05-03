"""SimHash for tier-3 content-based near-duplicate detection.

64-bit fingerprint over word 3-grams. Pairs with Hamming distance <= 3
are typically near-duplicates (rewrites of the same content).

No new dependencies — pure stdlib.
"""

from __future__ import annotations

import hashlib
import re

BITS = 64
DEFAULT_NGRAM = 3
DEFAULT_MAX_HAMMING = 3
MAX_CHARS_FOR_FEATURES = 8000  # cap content fed to tokenizer to keep cost bounded


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    return _WORD_RE.findall(text.lower())


def _shingles(text: str, n: int = DEFAULT_NGRAM) -> list[str]:
    text = text[:MAX_CHARS_FOR_FEATURES]
    words = _tokens(text)
    if len(words) < n:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def simhash(text: str, *, bits: int = BITS, ngram: int = DEFAULT_NGRAM) -> int:
    """Return a `bits`-bit SimHash of `text`. 0 if text empty."""
    feats = _shingles(text, n=ngram)
    if not feats:
        return 0
    counts = [0] * bits
    mask = (1 << bits) - 1
    for feat in feats:
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest(), 16) & mask
        for i in range(bits):
            if (h >> i) & 1:
                counts[i] += 1
            else:
                counts[i] -= 1
    fp = 0
    for i, c in enumerate(counts):
        if c > 0:
            fp |= 1 << i
    return fp


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_near_duplicate(
    a: int, b: int, *, max_distance: int = DEFAULT_MAX_HAMMING
) -> bool:
    """True if Hamming distance between two SimHashes is at most `max_distance`."""
    if a == 0 or b == 0:
        return False
    return hamming_distance(a, b) <= max_distance
