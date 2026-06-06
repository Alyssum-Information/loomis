# Docs index — Loomis

Loomis is a **local-first voice lifelogger**: plug in a USB recorder and it
auto-backs-up recordings, transcribes them with speaker labels, recognizes the
same voices across recordings, and turns them into a daily **diary** plus
standalone **meeting** records — all on-device by default
([01 §2](01-vision-and-scope.md#2-vision)). The numbered docs below are grouped
by role; the number is a stable file id, not a strict reading order.

## Foundations
| Doc | Title |
|---|---|
| 01 | [Vision & Scope](01-vision-and-scope.md) |
| 02 | [User Flows](02-user-flows.md) |
| 03 | [Requirements Specification](03-requirements-specification.md) |

## Architecture & Data
| Doc | Title |
|---|---|
| 04 | [System Architecture](04-system-architecture.md) |
| 05 | [Data Model & Storage](05-data-model-and-storage.md) |
| 06 | [Configuration](06-configuration.md) |
| 11 | [API Specification](11-api-specification.md) (backend ↔ frontend) |

## Feature specs
Gathered in [`features/`](features/), one per major capability, following the
processing pipeline ([04 §6](04-system-architecture.md#6-processing-pipeline)):

| Doc | Title | Traces |
|---|---|---|
| 01 | [Device Registration & Backup](features/01-device-registration-and-backup.md) | FR-1, FR-2 |
| 02 | [Audio Compression](features/02-audio-compression.md) | FR-3 |
| 03 | [Transcription](features/03-transcription.md) | FR-4 |
| 04 | [Speaker Diarization & Identification](features/04-speaker-diarization-and-identification.md) | FR-5 |
| 05 | [Summarization & Organization](features/05-summarization-and-organization.md) | FR-6 |
| 06 | [Cloud Sync](features/06-cloud-sync.md) | FR-8 |

## Experience
| Doc | Title |
|---|---|
| 07 | [UI / UX Design](07-ui-ux-design.md) |

## Operations
| Doc | Title |
|---|---|
| 08 | [Roadmap & Milestones](08-roadmap-and-milestones.md) |
| 09 | [Security & Privacy Model](09-security-and-privacy-model.md) |

## Reference
| Doc | Title |
|---|---|
| 10 | [Glossary](10-glossary.md) |
| — | [Architecture Decision Records](adr/README.md) (own `NNNN` numbering) |

## Maintaining these docs
- **Stable numbers.** A doc's number and `Doc ID` (`LM-NN`) are stable. **Add a
  new doc at the next-highest free number** — do not renumber existing docs to
  insert one. Reading/topic order is expressed by the grouping above, not by the
  file number; this keeps cross-references from breaking.
- **Feature specs have their own number series** inside `features/` (01–06 today;
  Doc IDs `LM-F0N`). The next feature is `07-...` in `features/`. Top-level docs
  are a separate series (01–10, Doc IDs `LM-NN`).
- **Cross-references** use `[NN Title](path)` (and optional `§x`); keep the number
  in the link text matching the target file's number. Links from `features/` to
  top-level docs use `../NN-...md`; top-level to a feature uses `features/0N-...md`.
- **Significant decisions get an [ADR](adr/README.md)**; supersede, don't rewrite.
