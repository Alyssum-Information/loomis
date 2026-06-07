# 0002 — Speech-to-text engine: WhisperX

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Transcription is the heart of the pipeline. Requirements: runs **locally**,
supports **Mandarin and many languages**, produces **word-level timestamps**
(needed to align diarization), and integrates cleanly with speaker diarization.

2026 landscape (surveyed June 2026):

- **NVIDIA Parakeet** — fastest and tops the Open ASR leaderboard on English
  word-error-rate (3–6× faster than Whisper), but **English-centric**: Parakeet
  V3 covers ~25 European languages and is weak/absent for Mandarin, Japanese,
  Arabic, etc.
- **OpenAI Whisper family** — 99 languages incl. Mandarin. Variants trade off:
  `faster-whisper` (CTranslate2; efficient CPU/GPU), `insanely-fast-whisper`
  (max throughput on high-end GPUs), **WhisperX** (adds forced alignment for
  accurate word timestamps **and** built-in pyannote diarization).
- **Moonshine** — small/fast, English-focused.

The user's recordings are **Mandarin + multilingual**, which rules out a
Parakeet-only path.

## Decision

Use **WhisperX** (faster-whisper backend) as the default STT engine, behind a
swappable `STTEngine` interface ([FR-4.4](../03-requirements-specification.md#fr-4-transcription)).

WhisperX gives us, in one tool: multilingual Whisper accuracy, word-level
timestamps via alignment, and **integrated pyannote diarization** — which also
satisfies much of [ADR-0007](0007-speaker-diarization-pyannote.md).

## Alternatives considered

| Option | Why not (as default) |
|--------|----------------------|
| Parakeet (+ Whisper fallback) | No reliable Mandarin; extra complexity routing by language. Revisit if usage becomes English-dominant. |
| faster-whisper alone | No alignment/diarization; we'd rebuild what WhisperX provides. |
| insanely-fast-whisper | Optimized for big GPUs; less aligned with local/modest hardware. |
| Cloud STT APIs | Violates local-first/privacy default. |

## Consequences

- **Pros:** strong Mandarin + multilingual accuracy; word timestamps;
  diarization included; GPU/CPU capable.
- **Cons:** heavier dependency stack (PyTorch, pyannote, alignment models);
  needs model downloads and benefits from a GPU.
- The `STTEngine` interface keeps Parakeet/other engines available later via
  config without touching the pipeline.
- Model size is configurable; `device = auto` picks CUDA when present, else CPU
  ([FR-4.5](../03-requirements-specification.md#fr-4-transcription)).

## References

- WhisperX — https://github.com/m-bain/whisperX
- faster-whisper — https://github.com/SYSTRAN/faster-whisper
- "Best open-source STT model in 2026 (benchmarks)" — Northflank
- "Choosing between Whisper variants" — Modal
