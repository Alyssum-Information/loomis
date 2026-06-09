# 02 · Feature — Audio Compression

| | |
|---|---|
| **Document** | Feature Spec — Audio Compression |
| **Doc ID** | LM-F02 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [01 Backup](01-device-registration-and-backup.md), [06 Configuration](../06-configuration.md), [ADR-0008](../adr/0008-audio-compression-opus.md) |
| **Traces** | FR-3.1 … FR-3.4 |

---

## 1. Overview

Optional transcoding of imported audio to **Opus** to drastically cut local
storage (often ~10× smaller than WAV) while keeping speech clear and
re-transcribable. Disabled by default.

## 2. Codec & command (FR-3.1, FR-3.2)

Opus via **ffmpeg** ([ADR-0008](../adr/0008-audio-compression-opus.md)):

```
ffmpeg -i <input> -c:a libopus -b:a <bitrate> -application <profile> <out>.opus
```

Defaults: `bitrate = 16k`, `application = voip` (speech-optimized). Both
configurable in `[transcode]`
([06 §2](../06-configuration.md#2-reference)). Typical speech range 12–24 kbps.

## 3. Policy (FR-3.4)

A per-recording policy, set globally and overridable per device
([05 §4.1](../05-data-model-and-storage.md#41-devices)):

| Policy | Keep original? | Store Opus? |
|--------|----------------|-------------|
| `keep_original` (default) | yes | no |
| `transcode_keep` | yes | yes |
| `transcode_only` | **no** (after verify) | yes |

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

**M1 behaviour:** the `transcode` step is enqueued **only** for the
`transcode_keep` / `transcode_only` policies; under `keep_original` STT reads the
original directly (no transcode). Producing a normalized/loudness-corrected copy
to feed STT even under `keep_original` is an optimisation deferred to a later
milestone (see §6) so the M1 path stays simple and avoids redundant work.

## 6. Open questions

- Whether to expose VBR vs CBR and per-device bitrate presets in the UI.
- Loudness normalization before STT (may improve transcription on quiet sources).
