"""Single source of truth for LM configuration.

All summarizers use whatever LM is configured here — swap provider in one place.

Env (provider-agnostic):

  AI_PROVIDER       ollama (default) | anthropic | openai | gemini | minimax
  SUMMARIZE_MODEL   provider-native model name (no prefix). Optional —
                    falls back to a sensible per-provider default.

Provider credentials (only the one matching AI_PROVIDER is read):

  OLLAMA_HOST       default http://localhost:11434
  ANTHROPIC_API_KEY
  OPENAI_API_KEY
  GEMINI_API_KEY
  MINIMAX_API_KEY

Under the hood we hand a `<litellm-prefix>/<model>` string to dspy.LM,
which DSPy passes through to LiteLLM. To add a new LiteLLM-supported
provider, add a row in `_PROVIDERS`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import dspy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Provider:
    litellm_prefix: str          # e.g. "ollama_chat", "anthropic", "openai"
    default_model: str           # used if SUMMARIZE_MODEL unset
    api_key_env: str | None      # None for ollama (local)


_PROVIDERS: dict[str, _Provider] = {
    "ollama":    _Provider("ollama_chat", "gemma4:latest",       None),
    "anthropic": _Provider("anthropic",   "claude-sonnet-4-6",   "ANTHROPIC_API_KEY"),
    "openai":    _Provider("openai",      "gpt-4o-mini",         "OPENAI_API_KEY"),
    "gemini":    _Provider("gemini",      "gemini-2.0-flash",    "GEMINI_API_KEY"),
    "minimax":   _Provider("minimax",     "abab6.5s-chat",       "MINIMAX_API_KEY"),
}

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def _build_lm(*, model_override: str | None = None) -> dspy.LM:
    name = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    spec = _PROVIDERS.get(name)
    if spec is None:
        supported = ", ".join(_PROVIDERS)
        raise RuntimeError(
            f"Unknown AI_PROVIDER={name!r}. Supported: {supported}."
        )

    model = (model_override or os.getenv("SUMMARIZE_MODEL") or spec.default_model).strip()
    full_model = f"{spec.litellm_prefix}/{model}"

    kwargs: dict[str, object] = {}
    if name == "ollama":
        host = (os.getenv("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")
        kwargs["api_base"] = host
        log.info("LM: %s @ %s", full_model, host)
    else:
        api_key = os.getenv(spec.api_key_env or "")
        if not api_key:
            raise RuntimeError(
                f"{spec.api_key_env} is required when AI_PROVIDER={name}"
            )
        kwargs["api_key"] = api_key
        log.info("LM: %s", full_model)

    return dspy.LM(model=full_model, **kwargs)


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
