# 0007 — Diarization & voiceprints: pyannote

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

We need (a) **diarization** — segmenting a recording by speaker turns — and (b)
**speaker embeddings** ("voiceprints") for cross-recording identity
([features/04 Speakers](../features/04-speaker-diarization-and-identification.md)). Meetings can have an
arbitrary number of participants, so a hard speaker cap is a problem.

2026 options surveyed:

- **pyannote 3.1** — strong accuracy (DER ~11–19% on standard benchmarks), large
  community, flexible speaker count, provides speaker-embedding models, and is
  **integrated into WhisperX** ([ADR-0002](0002-stt-engine-whisperx.md)).
- **NVIDIA NeMo Sortformer** — end-to-end, lower DER on some benchmarks, explicit
  overlap handling — **but currently a ~4-speaker limit**, impractical for
  general meetings, and pulls in the heavier NeMo stack.

## Decision

Use **pyannote 3.1** for diarization and speaker embeddings, obtained **via
WhisperX** so STT + alignment + diarization share one pipeline. Voiceprints are
L2-normalized embeddings compared by **cosine similarity**; cross-recording
identity logic lives in Loomis (not the library).

Vector search starts as **in-memory brute-force cosine** (fine for a personal
catalog) with a documented upgrade path to the **`sqlite-vec`** extension when
the identity set grows.

## Alternatives considered

- **NeMo Sortformer** — rejected as default due to the 4-speaker limit and
  heavier dependency; reconsider for ≤4-speaker scenarios if accuracy gains
  matter.
- **Building our own clustering on raw embeddings** — unnecessary; pyannote's
  pipeline is well-tuned. We still do *light* within-session clustering to fix
  over-segmentation.
- **Cloud diarization APIs** — rejected (local-first).

## Consequences

- **Pros:** flexible speaker count; mature; embeddings available; one pipeline
  with WhisperX; accuracy improves with user corrections feeding the voiceprint
  DB.
- **Cons:** pyannote models require accepting model licenses / Hugging Face
  tokens at setup; diarization is GPU-friendly but compute-heavy; DER is not
  zero — hence human-in-the-loop correction is a first-class feature
  ([FR-5.5](../03-requirements-specification.md#fr-5-diarization--speaker-identity)).
- The `memory → sqlite-vec` switch point is an open question tracked in the
  [roadmap](../08-roadmap-and-milestones.md).

## References

- pyannote.audio — https://github.com/pyannote/pyannote-audio
- "Best open-source speaker diarization models 2026" (NeMo vs pyannote)
- sqlite-vec — https://github.com/asg017/sqlite-vec
