"""Single source of truth for LM configuration.

All summarizers use whatever LM is configured here — swap provider in one place.

Switch provider via the `AI_PROVIDER` env var:

  AI_PROVIDER=ollama       (default) — local via Ollama
  AI_PROVIDER=anthropic    — Claude via Anthropic API (requires ANTHROPIC_API_KEY)
  AI_PROVIDER=openai       — GPT via OpenAI API (requires OPENAI_API_KEY)

To add a new provider: add a branch in `_build_lm()`. The `dspy.LM` constructor
takes any LiteLLM-supported `model=...` string, so most providers are a one-liner.

ENV (per provider):

  Ollama (default):
    OLLAMA_HOST | OLLAMA_URL  default http://localhost:11434
    OLLAMA_SUMMARIZE_MODEL    default gemma4:latest

  Anthropic:
    ANTHROPIC_API_KEY         required
    ANTHROPIC_MODEL           default claude-sonnet-4-6

  OpenAI:
    OPENAI_API_KEY            required
    OPENAI_MODEL              default gpt-4o
"""

from __future__ import annotations

import logging
import os

import dspy

log = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:latest"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o"


def _build_lm(*, model_override: str | None = None) -> dspy.LM:
    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()

    if provider == "ollama":
        host = (
            os.getenv("OLLAMA_HOST")
            or os.getenv("OLLAMA_URL")
            or DEFAULT_OLLAMA_HOST
        ).rstrip("/")
        model = (
            model_override
            or os.getenv("OLLAMA_SUMMARIZE_MODEL")
            or DEFAULT_OLLAMA_MODEL
        )
        log.info("LM: ollama_chat/%s @ %s", model, host)
        return dspy.LM(model=f"ollama_chat/{model}", api_base=host)

    if provider == "anthropic":
        model = (
            model_override
            or os.getenv("ANTHROPIC_MODEL")
            or DEFAULT_ANTHROPIC_MODEL
        )
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic"
            )
        log.info("LM: anthropic/%s", model)
        return dspy.LM(model=f"anthropic/{model}", api_key=api_key)

    if provider == "openai":
        model = (
            model_override
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        log.info("LM: openai/%s", model)
        return dspy.LM(model=f"openai/{model}", api_key=api_key)

    raise RuntimeError(
        f"Unknown AI_PROVIDER={provider!r}. Supported: ollama, anthropic, openai."
    )


def configure_lm(*, model_override: str | None = None) -> dspy.LM:
    """Configure DSPy globally with the LM the env says to use.

    Idempotent — safe to call again. Disables DSPy's default disk/memory cache
    so we don't get sticky stale outputs across pipeline runs.

    Returns the dspy.LM instance for callers that want to do things like
    `with dspy.context(lm=other_lm):` for one-off overrides.
    """
    lm = _build_lm(model_override=model_override)
    dspy.configure(lm=lm, adapter=dspy.JSONAdapter())
    dspy.configure_cache(enable_memory_cache=False, enable_disk_cache=False)
    return lm
