"""Semantic dedup tier 4 — embeddings via the configured AI provider.

Provider selection mirrors `pipeline/AI/lm.py`:

  EMBEDDING_PROVIDER  ollama (default) | openai | gemini | voyage | cohere
                      Falls back to AI_PROVIDER when unset. Anthropic and
                      Minimax have no first-party embedding API, so set
                      EMBEDDING_PROVIDER explicitly when AI_PROVIDER is
                      one of those.
  EMBEDDING_MODEL     provider-native model name (no prefix). Optional —
                      falls back to a sensible per-provider default.

Ollama goes through a direct httpx call (fast, batched, normalized in
place). Cloud providers route via LiteLLM (`litellm.embedding(...)`),
which is already pulled in as a DSPy dep.

Vectors are normalized to unit length so cosine == dot product.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

# Load .env from repo root so env vars are available even when this
# module is imported by a CLI that doesn't otherwise touch .env.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_THRESHOLD = 0.60

EMBED_DTYPE = np.float32
MAX_CHARS_FOR_EMBED = 4000
EMBED_BATCH_SIZE = 8
HTTP_TIMEOUT = httpx.Timeout(180.0, connect=10.0)


@dataclass(frozen=True)
class _EmbedProvider:
    default_model: str
    api_key_env: str | None
    litellm_prefix: str | None   # None for ollama (we use direct httpx)


_PROVIDERS: dict[str, _EmbedProvider] = {
    "ollama":  _EmbedProvider("qwen3-embedding:latest", None,             None),
    "openai":  _EmbedProvider("text-embedding-3-small", "OPENAI_API_KEY", "openai"),
    "gemini":  _EmbedProvider("text-embedding-004",     "GEMINI_API_KEY", "gemini"),
    "voyage":  _EmbedProvider("voyage-3",               "VOYAGE_API_KEY", "voyage"),
    "cohere":  _EmbedProvider("embed-english-v3.0",     "COHERE_API_KEY", "cohere"),
}


class OllamaError(RuntimeError):
    """Raised when the local Ollama daemon is unreachable or returns a bad reply."""


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider config is invalid or the call fails."""


def _resolve_provider() -> tuple[str, _EmbedProvider]:
    name = (
        os.environ.get("EMBEDDING_PROVIDER")
        or os.environ.get("AI_PROVIDER")
        or "ollama"
    ).strip().lower()
    spec = _PROVIDERS.get(name)
    if spec is None:
        supported = ", ".join(_PROVIDERS)
        raise EmbeddingError(
            f"Unknown EMBEDDING_PROVIDER={name!r} (or AI_PROVIDER fallback). "
            f"Supported: {supported}. Anthropic and Minimax have no embedding "
            f"API — set EMBEDDING_PROVIDER explicitly (e.g. ollama)."
        )
    return name, spec


def _config(model_override: str | None = None) -> tuple[str, _EmbedProvider, str]:
    name, spec = _resolve_provider()
    model = (model_override or os.environ.get("EMBEDDING_MODEL") or spec.default_model).strip()
    return name, spec, model


_NETWORK_ERRORS = (
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


def _ollama_url() -> str:
    return (os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_URL).rstrip("/")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_NETWORK_ERRORS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _post_embed_ollama(url: str, payload: dict) -> dict:
    try:
        resp = httpx.post(f"{url}/api/embed", json=payload, timeout=HTTP_TIMEOUT)
    except httpx.ConnectError as exc:
        raise OllamaError(
            f"Cannot reach Ollama at {url} — is the service running? ({exc})"
        ) from exc
    if resp.status_code == 404:
        model = payload.get("model")
        raise OllamaError(
            f"Ollama returned 404 for model {model!r}. "
            f"Pull it first: `ollama pull {model}`"
        )
    if resp.status_code >= 400:
        raise OllamaError(
            f"Ollama HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def _embed_via_litellm(model: str, prefix: str, api_key: str, inputs: list[str]) -> list[list[float]]:
    """Call a cloud embedding provider through LiteLLM. DSPy pulls litellm in already."""
    import litellm  # noqa: PLC0415 — keep import local so Ollama-only setups don't import litellm
    resp = litellm.embedding(model=f"{prefix}/{model}", input=inputs, api_key=api_key)
    return [row["embedding"] for row in resp["data"]]


def health_check(model: str | None = None) -> tuple[bool, str]:
    """Quick liveness probe. Returns (ok, message)."""
    name, spec, mdl = _config(model)
    try:
        if name == "ollama":
            data = _post_embed_ollama(_ollama_url(), {"model": mdl, "input": ["ok"]})
            embeds = data.get("embeddings") or []
        else:
            api_key = os.environ.get(spec.api_key_env or "")
            if not api_key:
                return False, f"{spec.api_key_env} is required when EMBEDDING_PROVIDER={name}"
            embeds = _embed_via_litellm(mdl, spec.litellm_prefix or "", api_key, ["ok"])
    except (OllamaError, EmbeddingError) as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if not embeds:
        return False, f"{name} responded but returned no embeddings"
    return True, f"OK — provider={name}, model={mdl}, dim={len(embeds[0])}"


def embed_texts(texts: list[str], *, model: str | None = None) -> np.ndarray:
    """Encode texts via the configured provider. Returns shape (N, dim) float32 unit vectors.

    Texts are truncated to MAX_CHARS_FOR_EMBED and batched. Embeddings are
    L2-normalized so cosine similarity reduces to a dot product.
    """
    if not texts:
        return np.empty((0, 0), dtype=EMBED_DTYPE)

    name, spec, mdl = _config(model)
    prepared = [t[:MAX_CHARS_FOR_EMBED] for t in texts]

    all_vecs: list[np.ndarray] = []
    for i in range(0, len(prepared), EMBED_BATCH_SIZE):
        chunk = prepared[i : i + EMBED_BATCH_SIZE]
        if name == "ollama":
            data = _post_embed_ollama(_ollama_url(), {"model": mdl, "input": chunk})
            embeds = data.get("embeddings") or []
        else:
            api_key = os.environ.get(spec.api_key_env or "")
            if not api_key:
                raise EmbeddingError(
                    f"{spec.api_key_env} is required when EMBEDDING_PROVIDER={name}"
                )
            embeds = _embed_via_litellm(mdl, spec.litellm_prefix or "", api_key, chunk)

        if len(embeds) != len(chunk):
            raise EmbeddingError(
                f"{name} returned {len(embeds)} embeddings for {len(chunk)} inputs "
                f"(model={mdl!r})"
            )
        for vec in embeds:
            all_vecs.append(np.asarray(vec, dtype=EMBED_DTYPE))

    arr = np.stack(all_vecs)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


def serialize(vec: np.ndarray) -> bytes:
    return vec.astype(EMBED_DTYPE).tobytes()


def deserialize(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=EMBED_DTYPE)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Both inputs assumed unit-normalized. Cosine == dot product."""
    return float(np.dot(a, b))


def is_semantic_match(
    a: np.ndarray, b: np.ndarray, *, threshold: float = DEFAULT_THRESHOLD
) -> bool:
    return cosine(a, b) >= threshold


def text_for_embedding(item: dict) -> str:
    """Build the text we encode per item (title + plain content, truncated)."""
    from pipeline.clean import for_embed

    title = (item.get("title") or "").strip()
    content = (item.get("content") or "").strip()
    is_html = bool(item.get("is_html")) or ("<" in content and ">" in content)
    return for_embed(content, is_html=is_html, title=title)


@dataclass
class EnsureEmbeddingsResult:
    """Outcome of ensure_recent_embeddings — small enough to log inline."""
    ok: bool = True
    examined: int = 0          # items in window
    already_embedded: int = 0
    newly_embedded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def ensure_recent_embeddings(store, *, days: int) -> EnsureEmbeddingsResult:
    """Pre-compute embeddings for every item in the dedup window that lacks one.

    Idempotent — items already embedded are skipped. Failures are captured
    per-batch and don't raise; dedup's own encoding fallback path catches any
    that this step missed.

    The point of running this BEFORE dedup (instead of letting dedup encode
    on the fly): if Ollama dies during encoding, only this stage fails, and
    dedup can still cluster on T1/T2/T3 with whatever embeddings exist. Also
    makes the embedding cost visible as its own stage in run logs instead of
    hidden inside dedup wall time.
    """
    result = EnsureEmbeddingsResult()
    try:
        rows = store.items_in_window(days=days)
    except Exception as exc:
        result.ok = False
        result.errors.append(f"items_in_window: {type(exc).__name__}: {exc}")
        return result

    result.examined = len(rows)
    needs: list[tuple[str, str]] = []
    for r in rows:
        blob = r["embedding"] if "embedding" in r.keys() else None
        if blob:
            result.already_embedded += 1
        else:
            it = dict(r)
            needs.append((it["id"], text_for_embedding(it)))

    if not needs:
        log.info(
            "ensure_embeddings: %d items in %d-day window, all already embedded — skipping",
            result.examined, days,
        )
        return result

    from pipeline.budget import BudgetWatch
    budget = BudgetWatch.for_stage("ensure_embeddings")
    log.info(
        "ensure_embeddings: %d/%d items in %d-day window need embedding (budget=%.0fs)",
        len(needs), result.examined, days, budget.budget_seconds,
    )

    # Process in the same EMBED_BATCH_SIZE chunks the dedup runner uses so
    # we get the same memory profile + per-batch failure granularity.
    deferred = 0
    for i in range(0, len(needs), EMBED_BATCH_SIZE):
        if budget.exceeded():
            deferred = len(needs) - i
            budget.log_exceeded(remaining_items=deferred)
            result.errors.append(
                f"budget_exceeded: ensure_embeddings {budget.elapsed():.0f}s "
                f">= {budget.budget_seconds:.0f}s; {deferred} item(s) deferred"
            )
            break
        chunk = needs[i : i + EMBED_BATCH_SIZE]
        ids = [iid for iid, _ in chunk]
        texts = [t for _, t in chunk]
        try:
            vecs = embed_texts(texts)
            for iid, vec in zip(ids, vecs):
                store.set_embedding(iid, serialize(vec))
                result.newly_embedded += 1
            store.commit()
        except Exception as exc:
            result.failed += len(chunk)
            result.errors.append(
                f"batch {i // EMBED_BATCH_SIZE}: {type(exc).__name__}: {exc}"
            )
            log.warning(
                "ensure_embeddings: batch %d (%d items) failed: %s",
                i // EMBED_BATCH_SIZE, len(chunk), exc,
            )
            # Keep going — dedup will retry whatever's still missing.

    log.info(
        "ensure_embeddings done: examined=%d already=%d new=%d failed=%d deferred=%d",
        result.examined, result.already_embedded, result.newly_embedded, result.failed, deferred,
    )
    if result.failed or deferred:
        # Partial success is still OK as long as something got embedded
        # (dedup will catch the rest on its own).
        result.ok = result.newly_embedded > 0
    return result
