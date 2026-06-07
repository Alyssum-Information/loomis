# 0005 — LLM provider abstraction, Ollama default

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Summaries (diary + meeting) and the classification confirmation step need an LLM.
Project goal: **local-first** — default to a local provider. But local model
quality is bounded by the user's hardware, and the user opted in to an **optional
cloud fallback** for higher-quality summaries when they choose.

## Decision

Define an `LLMProvider` interface and ship multiple implementations selected by
config ([FR-6.9](../03-requirements-specification.md#fr-6-summarization--organization)):

- **Default:** **Ollama** (local, private, offline). Model id configurable.
- **Optional:** cloud providers (OpenAI / Anthropic / Gemini), enabled only by
  explicit config.

The interface standardizes **structured output** (JSON-schema-validated via
pydantic, with retry on mismatch) so summaries are deterministic and storable
regardless of provider.

## Alternatives considered

- **Ollama-only** — rejected: the user wants the option of higher-quality cloud
  summaries; an abstraction costs little and future-proofs.
- **Cloud-only / cloud-default** — rejected: violates local-first/privacy
  defaults; cloud must be a deliberate opt-in.
- **LangChain-style mega-framework** — rejected for now: heavy dependency for
  what is a thin "prompt → structured JSON" need; revisit only if orchestration
  grows.

## Consequences

- **Pros:** private by default; pluggable quality/cost trade-off; provider-
  agnostic prompts and storage; easy to add providers.
- **Cons:** must normalize capabilities (context window, JSON-mode, tokenization)
  across providers; long inputs need chunking/map-reduce to fit local context
  windows (handled in [features/05 Summarization](../features/05-summarization-and-organization.md)).
- **Privacy:** enabling a cloud provider sends transcripts off-device. This
  crosses the trust boundary
  ([04 §10](../04-system-architecture.md#10-privacy--trust-boundary)) and **must** be
  surfaced in the UI ([FR-7.8](../03-requirements-specification.md#fr-7-user-interface)). Cloud API
  keys come from the environment, never stored in config or logs
  ([NFR-9](../03-requirements-specification.md#2-non-functional-requirements)).

## References

- Ollama — https://ollama.com
- Anthropic API, OpenAI API, Google Gemini API (optional adapters)
