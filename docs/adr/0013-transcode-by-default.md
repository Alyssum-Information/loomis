# 0013 — Transcode imports to Opus by default (32 kbps)

- **Status:** Accepted
- **Date:** 2026-06-10

## Context

[ADR-0008](0008-audio-compression-opus.md) chose Opus as the compression codec
but shipped it **off by default** (`keep_original`, 16 kbps when enabled). Real
usage surfaced three problems with that default:

1. **Unplayable originals.** Recorders write codecs browsers can't decode
   (ADPCM/A-law inside `.wav`), which forced a PCM preview cache just to play
   recordings in the UI.
2. **Storage.** Recorder WAVs run ~100–350 MB/hour; a lifelogger accumulates
   hours per day. The project explicitly does not chase audio fidelity
   ([01 §4](../01-vision-and-scope.md#4-non-goals-v1)).
3. **A wasted normalization point.** The transcode step already sits first in
   the pipeline; running it by default gives every downstream consumer (STT,
   diarization, the web player) one predictable format.

The open question was whether lossy compression hurts transcription. Published
measurements: Opus at 32 kbps costs roughly 0.1–2 % relative WER versus
uncompressed; degradation becomes visible below ~24 kbps and sharp at 16 kbps
and under (≈12 % relative in one multi-channel study). Whisper resamples
everything to 16 kHz mono internally, so format uniformity costs nothing.

## Decision

- **Default policy becomes `transcode_only`**: after the SHA-256-verified
  import, the original is transcoded to Opus, the output is **validated**
  (decodes, expected duration — FR-3.3), and only then is the library original
  replaced. The safety spine is unchanged; a failed transcode never deletes
  anything.
- **Default bitrate rises 16k → 32k** (`voip` profile, ~14 MB/hour): the
  STT-safe operating point per the measurements above.
- **Keeping originals stays one setting away** (FR-3.4): `transcode_keep`
  (store both) or `keep_original` (no transcode), globally
  (`[backup].transcode_policy`) or per source (`device.json`).

## Alternatives considered

- **Keep `keep_original` as the default** — preserves bit-exact archives, but
  the archive is unplayable in browsers, 10–25× larger, and fidelity is an
  explicit non-goal; users who want originals can still opt in.
- **16 kbps default** — halves the (already small) files but sits in the
  measurable-WER-loss zone; transcription quality is the product, storage is
  cheap.
- **Transcode only for playback (preview cache)** — what the previous fix did
  for ADPCM; it solves playback but not storage, and leaves STT consuming
  inconsistent inputs. The preview cache remains only for pre-existing
  library WAVs.

## Consequences

- New imports are browser-playable as-is — no preview transcode, no cache
  growth; `cache/preview/` only serves recordings imported before this change.
- STT, diarization, and voiceprints consume the same 32 kbps Opus; expected
  accuracy cost is ≈0–2 % relative WER, accepted per the non-goal.
- `transcode_only` requires ffmpeg/ffprobe (already baseline); without
  ffprobe the validation gate refuses deletion and the job parks — fail-safe.
- Existing libraries are untouched; the policy applies to new imports.
