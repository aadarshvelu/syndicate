"""Source-priority table and primary-selection rule for dedup clusters.

Lower number = higher priority (wins as cluster primary).

Tiers:
   10  official primary publisher (OpenAI, Anthropic, MIT, etc.)
   20  aggregator (HN search feeds — link to external article)
   30  newsletter / synthesis (TLDR, Import AI, etc.)
   99  unknown
"""

from __future__ import annotations

OFFICIAL = {
    "openai_news",
    "huggingface_blog",
    "anthropic",
    "meta_ai",
    "deepmind",
    "stanford_hai",
    "matt_levine",
    "economist_finance",
    "planet_money",
    "the_batch",
    "mit_tech_review",
}
AGGREGATOR = {
    "hn_llm_50",
    "hn_ai_100",
    "hn_ai_jobs_30",
    "hn_ai_startup_30",
}
NEWSLETTER = {
    "import_ai",
    "ahead_of_ai",
    "interconnects_ai",
    "noahpinion",
    "gradient_ascent",
    "normal_tech",
    "tldr_ai",
    "the_neuron",
}


def source_priority(source_id: str) -> int:
    if source_id in OFFICIAL:
        return 10
    if source_id in AGGREGATOR:
        return 20
    if source_id in NEWSLETTER:
        return 30
    return 99


def pick_primary(rows: list[dict]) -> str:
    """Given a cluster of items (each a dict-like row), return the id of the
    primary. Tiebreakers: longest content, then earliest date.
    """
    def score(r: dict) -> tuple[int, int, str]:
        prio = source_priority(r.get("source_id", ""))
        # Longer content wins → negate so smaller is better.
        clen = -len(r.get("content") or "")
        # Earliest date wins → ISO 8601 sorts lexicographically; smaller wins.
        date = r.get("date") or r.get("fetched_at") or "9999"
        return (prio, clen, date)

    return min(rows, key=score)["id"]
