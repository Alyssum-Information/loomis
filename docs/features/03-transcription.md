# 03 · Feature — Transcription

| | |
|---|---|
| **Document** | Feature Spec — Transcription |
| **Doc ID** | LM-F03 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
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

Auto-detect by default; Mandarin and 99 languages supported — but **set
`[stt].language` (e.g. `"zh"`) unless you genuinely record in many languages.**
Whisper detects the language from the first ~30 seconds of each file, so
lifelogger clips that open with silence, noise, or a stray foreign phrase
misdetect easily, and a misdetected file is transcribed *and aligned* in the
wrong language end to end. Forcing the language eliminates this failure mode,
skips the detection pass, and selects the right alignment model up front. A
user's daily language rarely changes (`config.toml`, or
`LOOMIS_STT__LANGUAGE=zh`), so this is the recommended setting.

Already-misdetected recordings are repairable after the fact: the pipeline is
idempotent, so `POST /recordings/{id}/retranscribe` (the Recording page's
**Re-transcribe** button) or the bulk
`POST /recordings/retranscribe {"not_language": "zh"}` re-runs STT and
everything downstream — diarization, speaker identity, and the affected days'
diaries/meetings all rebuild ([11 §3.2](../11-api-specification.md#32-recordings--transcripts)).

### 3.1 Input preprocessing — evaluated, mostly already covered

Assessed against WhisperX's own pipeline and published measurements
([ADR-0013](../adr/0013-transcode-by-default.md) covers the compression side):

| Candidate | Verdict | Why |
|-----------|---------|-----|
| **Segmentation / VAD** | already built in | WhisperX runs pyannote VAD before Whisper, cutting audio to speech-only windows — its headline trick (reduces hallucination + enables batching, no WER cost). Nothing to add. |
| **Resample / mono mixdown** | already built in | `whisperx.load_audio` decodes everything to 16 kHz mono float32 via ffmpeg; input format/levels are normalized before the model sees them. |
| **Denoising** | rejected by default | Whisper trains on noisy audio; published results are mixed and aggressive filtering removes consonant/tonal cues, *hurting* accuracy. Revisit per-source as an opt-in only if a concrete noisy-device case shows gains. |
| **Loudness normalization** | not needed | Whisper applies log-mel normalization internally; RMS-normalized input measures within noise of baseline. |

Net: no preprocessing stage is added. The high-leverage levers for quality are
the forced **language** (§3), the **model size** (§5), and keeping the bitrate
at/above the 32 kbps STT-safe point (feature 02 §2).

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
