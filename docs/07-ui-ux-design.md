# 07 · UI / UX Design

| | |
|---|---|
| **Document** | UI / UX Design |
| **Doc ID** | LM-07 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [02 Flows §6](02-user-flows.md#6-browse--review-ui), [04 Architecture](04-system-architecture.md), [11 API](11-api-specification.md), [features/04 Speakers](features/04-speaker-diarization-and-identification.md), [ADR-0003](adr/0003-frontend-vue-spa.md) |
| **Traces** | FR-7.1 … FR-7.8 |

---

## 1. Overview

A **Vue 3 + Vuetify single-page app** (in [`web/`](04-system-architecture.md#12-repository-layout))
that observes and controls the background daemon **over the local REST/WebSocket
API** ([11 API Specification](11-api-specification.md)). The SPA holds no business
logic and never touches SQLite or the file library directly: it reads via REST,
issues commands that enqueue jobs, and receives live updates over a WebSocket.
Default bind `127.0.0.1`; LAN exposure opt-in. Rationale:
[ADR-0003](adr/0003-frontend-vue-spa.md).

Built with Vite; state via Pinia; the API client is generated from the backend's
OpenAPI schema so the contract stays typed end-to-end.

## 2. Information architecture

| Screen | Purpose | FR |
|--------|---------|----|
| **Dashboard** | Recent activity, pending egress warnings, job health summary | 7.6, 7.8 |
| **Timeline / Calendar** | Days with diary entry + meeting chips; the lifelog spine | 7.2 |
| **Recording detail** | Audio player + speaker-labeled transcript, jump-to-time | 7.3 |
| **Diary entry** | Rendered daily entry; links to source clips and meetings | 7.2 |
| **Meeting record** | Attendees, summary, decisions, action items | 7.2 |
| **Speakers** | List/confirm/rename/merge/split identities | 7.4 |
| **Search** | Full-text across transcripts, diaries, meetings | 7.5 |
| **Jobs / Health** | Queued/running/failed steps; retry controls | 7.6 |
| **Devices** | Registered devices; per-device settings | 7.7, 1.7 |
| **Settings** | Defaults, models, cloud remotes | 7.7 |

## 3. Key interactions

- **New device prompt** (FR-1.3): banner on connect of an unregistered volume →
  registration form ([features/01](features/01-device-registration-and-backup.md)).
- **Speaker correction** (FR-5.5): inline on the transcript and on the Speakers
  screen; merge/split with undo; feeds the voiceprint flywheel
  ([features/04 §6](features/04-speaker-diarization-and-identification.md#6-human-in-the-loop-fr-55-fr-56)).
- **Re-summarize day** (FR-6.8): `POST /diary/{date}/resummarize` → job;
  progress over WebSocket.
- **Sync now** (FR-8.3): `POST /cloud/sync` → job, with live progress.

Each command maps to an API endpoint ([11 §3](11-api-specification.md#3-rest-resources-v1));
heavy actions return `202` + a `job_id` and stream status over the WebSocket
rather than blocking the UI.

## 4. Egress transparency (FR-7.8) ⚠️

Any action or setting that will send data off-device — enabling a cloud LLM,
enabling cloud sync, binding the API to `0.0.0.0` — is visually flagged before it
takes effect, driven by `egress.pending` WebSocket events
([11 §4](11-api-specification.md#4-websocket-apiv1ws)). This is a hard
requirement, not a nicety; see
[09 Security & Privacy](09-security-and-privacy-model.md).

## 5. Principles

- **Browsing-first.** The timeline is the product's heart; optimize for scanning
  and reading, not data entry.
- **Show the machine's state.** Queued/running/failed work is always visible
  (NFR-7) — no silent processing.
- **Non-destructive.** Speaker merge/split and re-summary keep prior state
  recoverable.

## 6. Open questions

- Audio waveform vs simple seek bar for the player.
- Timeline density controls (day / week / month views).
- Optional system-tray shell wrapping the SPA, or shipping it inside a desktop
  wrapper (backlog — [08 Roadmap](08-roadmap-and-milestones.md)).
- Whether the backend serves the built SPA or it is hosted separately
  ([11 §6](11-api-specification.md#6-open-questions)).
