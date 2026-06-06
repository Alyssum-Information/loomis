# 04 · Feature — Speaker Diarization & Identification

| | |
|---|---|
| **Document** | Feature Spec — Speaker Diarization & Identification |
| **Doc ID** | LM-F04 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [03 Transcription](03-transcription.md), [05 Summarization](05-summarization-and-organization.md), [05 Data Model](../05-data-model-and-storage.md), [ADR-0007](../adr/0007-speaker-diarization-pyannote.md), [09 Security](../09-security-and-privacy-model.md) |
| **Traces** | FR-5.1 … FR-5.7 |

---

## 1. Overview

Two related problems:

- **Diarization** — *within one recording*, who spoke when (labels like
  `SPEAKER_00`). (FR-5.1)
- **Identification** — *across recordings*, is this the same person? Gives them a
  stable identity via a **voiceprint database**. (FR-5.2–5.4)

Stable identities power meeting attendee/action-item attribution, a consistent
first-person diary voice, and the diary-vs-meeting decision
([11](05-summarization-and-organization.md)).

## 2. Pipeline position

```
diarize ──▶ per-turn embeddings ──▶ speaker_id ──▶ identity per segment
(pyannote)   (FR-5.2)                (match/enroll)  (writes segments.speaker_id)
```

## 3. Diarization (FR-5.1)

**pyannote 3.1**, obtained via WhisperX so STT + alignment + diarization share
one pipeline ([ADR-0007](../adr/0007-speaker-diarization-pyannote.md)). Flexible
speaker count (no hard cap), tunable via `[diarization].min/max_speakers`.

## 4. Voiceprints (FR-5.2)

Per diarized speaker, aggregate their audio and compute a fixed-length
**embedding** (pyannote/ECAPA-TDNN class), L2-normalized so **cosine similarity**
is the metric. Stored in `voiceprints` with provenance
([05 §4.6](../05-data-model-and-storage.md#46-voiceprints--cross-recording-identity-index)).
Multiple voiceprints accumulate per identity, improving robustness.

## 5. Matching algorithm (FR-5.3, FR-5.4)

For each unknown embedding `e`:

1. Cosine-compare `e` against each known speaker's centroid / k-NN voiceprints.
2. `best` = top similarity, `second` = runner-up.
3. Decide with three thresholds (`[speaker_id]` config):
   - `best ≥ match_threshold` **and** `best − second ≥ margin` → **assign**; add
     `e` as a new voiceprint.
   - `best < new_identity_below` → **create provisional identity**.
   - in-between → **uncertain**: assign provisionally, flag for review.
4. The device `owner_speaker_hint` is a prior for the dominant voice.

Defaults ship conservative — prefer a new provisional identity over a wrong merge
(merging is cheap for the user; un-merging is annoying).

Optional **within-session clustering** consolidates diarization
over-segmentation before global matching.

## 6. Human-in-the-loop (FR-5.5, FR-5.6)

The UI ([07](../07-ui-ux-design.md)) lets the user **name**, **confirm/correct**,
**merge**, and **split** identities. Every correction writes back as
curated/additional voiceprints, so future matching improves — the accuracy
flywheel.

## 7. Enrollment (FR-5.7)

Optional: enroll a known voice from a labeled clip to seed an identity before it
appears in recordings.

## 8. Search scaling

Start **in-memory brute-force cosine** (fine for hundreds–thousands of
identities); upgrade path to the
[`sqlite-vec`](https://github.com/asg017/sqlite-vec) extension
(`[speaker_id].vector_backend = "sqlite-vec"`) keeping the single-file local-first
story. Switch point is an open question in the
[roadmap](../08-roadmap-and-milestones.md).

## 9. Privacy

Voiceprints are biometric-adjacent. Stored **locally** like all data; never
uploaded unless the user explicitly includes the DB in a cloud sync scope. See
[09 Security & Privacy](../09-security-and-privacy-model.md).
