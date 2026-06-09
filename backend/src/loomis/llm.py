"""LLM provider behind a swappable interface (FR-6.9, ADR-0005).

Local-first: the default ``ollama`` provider talks to a local Ollama server; a
dep-free ``null`` provider returns an empty JSON object so offline/CI runs produce
valid (empty) structured output without a model or network. Cloud providers are a
future opt-in (their keys come from the environment, never config — NFR-9).

``complete_structured`` standardizes the "prompt → schema-validated JSON" need:
it asks for JSON mode and retries on a validation mismatch, so callers get a typed
pydantic object regardless of provider.
"""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic import BaseModel, ValidationError

from .config import LlmSettings

log = logging.getLogger(__name__)


class LLMProvider(Protocol):
    name: str
    model: str | None

    def complete(self, prompt: str, *, json_mode: bool) -> str: ...


class NullProvider:
    """Offline stub: an empty JSON object. Every summary schema defaults, so it validates."""

    name = "null"
    model: str | None = None

    def complete(self, prompt: str, *, json_mode: bool) -> str:
        return "{}"


class OllamaProvider:
    """Local Ollama via its HTTP API; ``httpx`` is imported lazily (the ``llm`` extra)."""

    name = "ollama"

    def __init__(self, settings: LlmSettings) -> None:
        self.model: str | None = settings.model
        self._host = settings.host.rstrip("/")
        self._timeout = settings.timeout_s

    def complete(self, prompt: str, *, json_mode: bool) -> str:
        import httpx  # noqa: PLC0415

        payload: dict[str, object] = {"model": self.model, "prompt": prompt, "stream": False}
        if json_mode:
            payload["format"] = "json"
        resp = httpx.post(f"{self._host}/api/generate", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return str(resp.json().get("response", ""))


def get_provider(settings: LlmSettings) -> LLMProvider:
    """Construct the LLM provider named by ``[llm].provider``."""
    if settings.provider == "null":
        return NullProvider()
    if settings.provider == "ollama":
        return OllamaProvider(settings)
    raise ValueError(f"unknown llm provider: {settings.provider!r}")


def model_id(provider: LLMProvider) -> str:
    """Stable identifier stored with each summary for reproducibility (feature 05 §5)."""
    return f"{provider.name}:{provider.model}" if provider.model else provider.name


def complete_structured[T: BaseModel](
    provider: LLMProvider, prompt: str, schema: type[T], *, max_retries: int
) -> T:
    """Prompt for JSON and validate into ``schema``, retrying on mismatch (feature 05 §5)."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        raw = provider.complete(prompt, json_mode=True)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc
            log.warning("structured output invalid (attempt %d/%d)", attempt + 1, max_retries + 1)
    raise ValueError(f"LLM did not return valid {schema.__name__}: {last_error}")
