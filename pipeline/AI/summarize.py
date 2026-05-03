"""AI-powered item enrichment — teaser, summary, importance, category.

Populates four DB columns on is_primary=1 items using a local Ollama
generative model via its native /api/chat endpoint with structured output
(format=json_schema). Same httpx+tenacity pattern as dedup/semantic.py.

Swap model via OLLAMA_SUMMARIZE_MODEL env var or --model CLI flag.

Future cloud provider: swap _ollama_chat() for an Anthropic/OpenAI call —
the Pydantic schema (ItemSummary) and pipeline loop are provider-agnostic.

ENV:
  OLLAMA_URL              default http://localhost:11434
  OLLAMA_SUMMARIZE_MODEL  default gemma4:latest
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.clean import for_llm
from pipeline.storage import DEFAULT_DB_PATH, ItemStore, now_iso

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemma4:latest"
MAX_TOTAL_CHARS = 8_000
COMMIT_EVERY = 10
HTTP_TIMEOUT = httpx.Timeout(3000.0, connect=30.0)  # generative models can be slow

# Only retry on network-level failures, not timeouts (slow model won't recover on retry).
_NETWORK_ERRORS = (
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

_CATEGORIES = ["ai_research", "ai_products", "economics", "policy", "startup", "world_news", "tech_news", "other"]

# Flat schema — no $defs, no $ref. Ollama's format param requires a plain object schema.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "teaser":    {"type": "string"},
        "summary":   {"type": "string"},
        "importance": {"type": "integer"},
        "category":  {"type": "string", "enum": _CATEGORIES},
    },
    "required": ["key_facts", "teaser", "summary", "importance", "category"],
}

Category = Literal[
    "ai_research", "ai_products", "economics",
    "policy", "startup", "world_news", "tech_news", "other",
]


class ItemSummary(BaseModel):
    key_facts: list[str]
    teaser: str
    summary: str
    importance: int = Field(ge=1, le=5)
    category: Category


@dataclass
class SummarizeResult:
    channel: str = "summarize"
    started_at: str = ""
    finished_at: str = ""
    examined: int = 0
    summarized: int = 0
    skipped: int = 0
    ok: bool = True
    errors: list[str] = field(default_factory=list)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_NETWORK_ERRORS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _ollama_chat(url: str, model: str, prompt: str, schema: dict) -> str:
    """POST to Ollama /api/chat with structured output. Returns raw JSON string."""
    resp = httpx.post(
        f"{url}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "think": False,  # disable Qwen3 chain-of-thought thinking tokens
        },
        timeout=HTTP_TIMEOUT,
    )
    log.debug("Ollama raw response: %s", resp.text[:500])
    if resp.status_code == 404:
        raise RuntimeError(
            f"Model {model!r} not found on Ollama. Pull it: `ollama pull {model}`"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
    content = resp.json()["message"]["content"]
    # Strip markdown code fences some models wrap around JSON output
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[: content.rfind("```")]
    return content.strip()


def _build_content(primary_content: str, member_contents: list[str]) -> str:
    parts = [primary_content] + [m for m in member_contents if m]
    if len(parts) == 1:
        return parts[0][:MAX_TOTAL_CHARS]
    budget = MAX_TOTAL_CHARS // len(parts)
    return "\n\n---\n\n".join(p[:budget] for p in parts)[:MAX_TOTAL_CHARS]


def _build_prompt(title: str, content: str, source_count: int) -> str:
    lines = [
        "You are a news analyst. Analyze the article and return a JSON object with these fields:",
        "",
        "key_facts: array of up to 8 verbatim facts extracted from the article (names, orgs, numbers, dates, key claims)",
        "teaser: one compelling hook (≤150 chars) using the single most surprising fact",
        "summary: ≤450 chars, inverted pyramid — most important first, then context; explain jargon once; include all key_facts",
        "importance: integer 1-5 (5=major breaking news, 1=routine/minor)",
        f"category: one of: {', '.join(_CATEGORIES)}",
    ]
    if title:
        lines += ["", f"Article title: {title}"]
    if source_count > 1:
        lines += [f"Sources covering this story: {source_count}"]
    lines += ["", "Article:", content]
    return "\n".join(lines)


class SummarizePipeline:
    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        model: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.model = (
            model
            or os.environ.get("OLLAMA_SUMMARIZE_MODEL")
            or DEFAULT_MODEL
        )

    def run(self, *, limit: int = 100) -> SummarizeResult:
        ollama_url = (
            os.environ.get("OLLAMA_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        ).rstrip("/")

        result = SummarizeResult(started_at=now_iso())

        try:
            with ItemStore(self.db_path) as store:
                items = store.items_needing_summary(limit=limit)
                result.examined = len(items)
                log.info("Summarize: %d items to process (model=%s)", result.examined, self.model)

                for i, row in enumerate(items):
                    item = dict(row)
                    raw_content = item.get("content") or ""
                    if not raw_content.strip():
                        result.skipped += 1
                        continue

                    # Clean HTML for existing rows saved before normalize.py change
                    primary_content = for_llm(raw_content, is_html=bool(item.get("is_html")))

                    cluster_id = item.get("cluster_id")
                    member_contents: list[str] = []
                    cluster_size = 1
                    if cluster_id:
                        member_contents, cluster_size = store.cluster_members_content(
                            cluster_id, exclude_id=item["id"]
                        )

                    content = _build_content(primary_content, member_contents)
                    prompt = _build_prompt(
                        title=(item.get("title") or "").strip(),
                        content=content,
                        source_count=cluster_size,
                    )

                    try:
                        raw = _ollama_chat(ollama_url, self.model, prompt, _OUTPUT_SCHEMA)
                        out = ItemSummary.model_validate(json.loads(raw))
                    except (RuntimeError, json.JSONDecodeError, ValidationError) as exc:
                        log.warning(
                            "Failed for %r: %s",
                            (item.get("title") or "")[:50], exc,
                        )
                        result.skipped += 1
                        continue

                    if not out.teaser or not out.summary:
                        result.skipped += 1
                        continue

                    importance = min(5, out.importance + 1) if cluster_size >= 3 else out.importance

                    store.set_enrichment(
                        item["id"],
                        teaser=out.teaser[:150],
                        summary=out.summary[:450],
                        importance=importance,
                        category=out.category,
                    )
                    result.summarized += 1
                    log.info(
                        "[%d/%d] %s | imp=%d cat=%s",
                        i + 1, result.examined,
                        (item.get("title") or "")[:60],
                        importance, out.category,
                    )

                    if (i + 1) % COMMIT_EVERY == 0:
                        store.commit()

                store.commit()

        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
            result.ok = False
            log.exception("SummarizePipeline crashed")

        result.finished_at = now_iso()
        return result
