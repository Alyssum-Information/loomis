# 03 · Feature — Transcription

| | |
|---|---|
| **Document** | Feature Spec — Transcription |
| **Doc ID** | LM-F03 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [04 Speakers](04-speaker-diarization-and-identification.md), [05 Data Model](../05-data-model-and-storage.md), [ADR-0002](../adr/0002-stt-engine-whisperx.md) |
| **Traces** | FR-4.1 … FR-4.5 |

---

## 1. Overview

Convert each recording into a **time-aligned, multilingual transcript** with
word-level timestamps — the substrate for diarization, speaker ID, search, and
summaries.

## 2. Engine (FR-4.4)

Default **WhisperX** (faster-whisper backend) behind an `STTEngine` interface
([ADR-0002](../adr/0002-stt-engine-whisperx.md)). WhisperX gives multilingual
Whisper accuracy **plus** forced alignment for accurate word timestamps **plus**
integrated pyannote diarization (consumed in
[10](04-speaker-diarization-and-identification.md)).

The interface keeps other engines (Parakeet for English-heavy use, etc.)
swappable via `[stt].engine`.

## 3. Language (FR-4.2)

Auto-detect by default; Mandarin and 99 languages supported. Can be forced via
`[stt].language` (e.g. `"zh"`) when known, which is faster and more reliable than
detection on short clips.

## 4. Output (FR-4.1, FR-4.3)

- Full transcript JSON → `transcripts/<recording_id>.json` (words + timestamps +
  diarization labels).
- `transcripts` row (engine, model, language, plain text for search) +
  `segments` rows (the queryable, time-aligned index). Schema:
  [05 §4.3–4.4](../05-data-model-and-storage.md#43-transcripts).

## 5. Hardware (FR-4.5)

`[stt].device = auto` selects CUDA when present, else CPU; `compute_type`
(e.g. `float16` GPU / `int8` CPU) and `model` (e.g. `large-v3` vs `medium`) are
configurable to fit the machine. Models load lazily and can unload when idle
([04 §7](../04-system-architecture.md#7-concurrency--durability-model)).

## 6. Pipeline position

`stt` step, after optional `transcode`, before `diarize`
([04 §6](../04-system-architecture.md#6-processing-pipeline)). GPU-heavy steps are
serialized/capped to avoid VRAM thrash.

## 7. Open questions

- Long-recording chunking strategy and overlap handling.
- Optional manual transcript correction in the UI (feeds nothing automated, but
  improves search/summaries).
