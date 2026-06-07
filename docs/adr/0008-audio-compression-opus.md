# 0008 — Audio compression: Opus

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Feature #3 wants an **optional** high-compression archive format to drastically
cut local storage for backed-up recordings, while keeping speech intelligible
(and good enough to re-transcribe if needed).

## Decision

Use the **Opus** codec via **ffmpeg** (`libopus`) for optional transcoding, with
a speech-optimized profile by default:

```
ffmpeg -i input.wav -c:a libopus -b:a 16k -application voip output.opus
```

Bitrate (typ. 12–24 kbps for speech) and the `voip` application profile are
configurable ([06 Configuration](../06-configuration.md)). Transcoding sits behind a
per-device policy: `keep_original` / `transcode_keep` / `transcode_only`
([FR-3](../03-requirements-specification.md#fr-3-audio-compression-optional)).

## Alternatives considered

| Option | Why not |
|--------|---------|
| MP3 | Larger at equal speech quality; older; worse low-bitrate behavior. |
| AAC/M4A | Good, but Opus beats it at low (speech) bitrates and is fully open. |
| FLAC | Lossless = large; defeats the space-saving goal. |
| Keep WAV | No compression; the problem we're solving. |

Library binding: **shell out to ffmpeg** rather than PyAV — ffmpeg is ubiquitous,
simple to invoke, and avoids a heavier native binding; PyAV remains an option if
in-process control is later needed.

## Consequences

- **Pros:** best-in-class speech compression (often ~10× smaller than WAV);
  open standard (RFC 6716); great quality at low bitrates with `voip`.
- **Cons:** **lossy** — originals are gone under `transcode_only` (which is why
  deletion is gated and opt-in); requires the **ffmpeg binary** present.
- **Safety:** the transcode output is validated (decodable, expected duration)
  **before** any original is deleted
  ([FR-3.3](../03-requirements-specification.md#fr-3-audio-compression-optional),
  [04 §8](../04-system-architecture.md#8-data-integrity-the-safety-spine)).

## References

- Opus — https://opus-codec.org/ · Recommended settings — https://wiki.xiph.org/Opus_Recommended_Settings
- ffmpeg libopus — https://ffmpeg.org/ffmpeg-codecs.html
