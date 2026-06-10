# 02 · Feature — Audio Compression

| | |
|---|---|
| **Document** | Feature Spec — Audio Compression |
| **Doc ID** | LM-F02 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [01 Backup](01-device-registration-and-backup.md), [06 Configuration](../06-configuration.md), [ADR-0008](../adr/0008-audio-compression-opus.md), [ADR-0013](../adr/0013-transcode-by-default.md) |
| **Traces** | FR-3.1 … FR-3.4 |

---

## 1. Overview

Transcoding of imported audio to **Opus** — drastically smaller (often ~10×
vs WAV), browser-playable, and speech-clear. **On by default** since
[ADR-0013](../adr/0013-transcode-by-default.md): the validated Opus replaces
the original in the library; keeping originals is a per-source or global
opt-in (§3).

## 2. Codec & command (FR-3.1, FR-3.2)

Opus via **ffmpeg** ([ADR-0008](../adr/0008-audio-compression-opus.md)):

```
ffmpeg -i <input> -c:a libopus -b:a <bitrate> -application <profile> <out>.opus
```

Defaults: `bitrate = 32k`, `application = voip` (speech-optimized). Both
configurable in `[transcode]` ([06 §2](../06-configuration.md#2-reference)).
32 kbps is the STT-safe point: published measurements put Opus@32k at ≈0.1–2 %
relative WER vs uncompressed, with visible degradation only below ~24 kbps
([ADR-0013](../adr/0013-transcode-by-default.md)).

## 3. Policy (FR-3.4)

A per-recording policy, set globally and overridable per device
([05 §4.1](../05-data-model-and-storage.md#41-devices)):

| Policy | Keep original? | Store Opus? |
|--------|----------------|-------------|
| `keep_original` | yes | no |
| `transcode_keep` | yes | yes |
| `transcode_only` (**default**, [ADR-0013](../adr/0013-transcode-by-default.md)) | **no** (after verify) | yes |

## 4. Integrity (FR-3.3) ⚠️

Before any original is deleted (under `transcode_only`), the Opus output is
**validated**: it must decode and have the expected duration. This validation is
step 6 of the backup safety spine
([07 §4](01-device-registration-and-backup.md#4-backup--ingest-fr-21--fr-28)).
A failed transcode never triggers source deletion.

> Validation uses `ffprobe`; if it is unavailable the transcode cannot be verified,
> so `transcode_only` safely refuses to delete the original (the job parks instead).

## 5. Pipeline position

`transcode` is the first job step
([04 §6](../04-system-architecture.md#6-processing-pipeline)).

The `transcode` step is enqueued for the `transcode_keep` / `transcode_only`
policies; under `keep_original` STT reads the original directly (no transcode).
With transcoding on by default, every downstream consumer — STT, diarization,
voiceprints, the web player — sees one predictable format, and the player's
PCM preview cache is only needed for recordings imported before
[ADR-0013](../adr/0013-transcode-by-default.md).

## 6. Open questions

- Whether to expose VBR vs CBR and per-device bitrate presets in the UI.
- ~~Loudness normalization before STT~~ — evaluated and rejected for the default
  path; see [feature 03 §3.1](03-transcription.md).
