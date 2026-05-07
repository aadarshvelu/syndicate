"""Semantic dedup tier 4 — embeddings via local Ollama HTTP endpoint.

Configured via env (`.env` is loaded automatically):
  OLLAMA_URL          default http://localhost:11434
  OLLAMA_EMBED_MODEL  default qwen3-embedding:latest

No local model deps — just httpx + numpy. The Ollama service must be
running and have the model pulled (`ollama pull qwen3-embedding:latest`).
Vectors are normalized to unit length so cosine == dot product.
"""

from __future__ import annotations

import logging
import os
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

# Load .env from repo root so OLLAMA_URL etc. are available even when this
# module is imported by a CLI that doesn't otherwise touch .env.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3-embedding:latest"
DEFAULT_THRESHOLD = 0.60

EMBED_DTYPE = np.float32
MAX_CHARS_FOR_EMBED = 4000
EMBED_BATCH_SIZE = 8
HTTP_TIMEOUT = httpx.Timeout(180.0, connect=10.0)


class OllamaError(RuntimeError):
    pass


def _config(model_override: str | None = None) -> tuple[str, str]:
    url = (os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or DEFAULT_URL).rstrip("/")
    model = model_override or os.environ.get("OLLAMA_EMBED_MODEL") or os.environ.get("OLLAMA_MODEL_QWEN_EMBEDDING") or DEFAULT_MODEL
    return url, model


_NETWORK_ERRORS = (
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_NETWORK_ERRORS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _post_embed(url: str, payload: dict) -> dict:
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


def health_check(model: str | None = None) -> tuple[bool, str]:
    """Quick liveness probe. Returns (ok, message)."""
    url, mdl = _config(model)
    try:
        data = _post_embed(url, {"model": mdl, "input": ["ok"]})
    except OllamaError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    embeds = data.get("embeddings") or []
    if not embeds:
        return False, "Ollama responded but returned no embeddings"
    return True, f"OK — model={mdl}, dim={len(embeds[0])}"


def embed_texts(texts: list[str], *, model: str | None = None) -> np.ndarray:
    """Encode texts via Ollama. Returns shape (N, dim) float32 unit vectors.

    Texts are truncated to MAX_CHARS_FOR_EMBED and batched. Embeddings are
    L2-normalized so cosine similarity reduces to a dot product.
    """
    if not texts:
        return np.empty((0, 0), dtype=EMBED_DTYPE)

    url, mdl = _config(model)
    prepared = [t[:MAX_CHARS_FOR_EMBED] for t in texts]

    all_vecs: list[np.ndarray] = []
    for i in range(0, len(prepared), EMBED_BATCH_SIZE):
        chunk = prepared[i : i + EMBED_BATCH_SIZE]
        data = _post_embed(url, {"model": mdl, "input": chunk})
        embeds = data.get("embeddings") or []
        if len(embeds) != len(chunk):
            raise OllamaError(
                f"Ollama returned {len(embeds)} embeddings for {len(chunk)} inputs "
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
