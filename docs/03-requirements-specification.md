# 03 · Requirements Specification

| | |
|---|---|
| **Document** | Software Requirements Specification (SRS) |
| **Doc ID** | LM-03 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [02 User Flows](02-user-flows.md), [04 Architecture](04-system-architecture.md), [features/](features/) |
| **Traces** | Defines FR-1 … FR-9, NFR-1 … NFR-11 |

---

Requirements are derived from the [user flows](02-user-flows.md). Each functional
requirement has a stable ID (`FR-x.y`) so design, code, and tests can reference
it. Priority uses [MoSCoW](https://en.wikipedia.org/wiki/MoSCoW_method): **M**ust,
**S**hould, **C**ould, **W**on't (this release).

## 1. Functional requirements

### FR-1 Source detection & registration
*Spec: [features/01](features/01-device-registration-and-backup.md)*

A **source** is anywhere recordings arrive from: a USB recorder volume, or a
local **folder** that some other tool keeps filled (phone sync via
Syncthing/OneDrive/iCloud, a lifelogger's companion app, manual drops). Both
kinds register into the same `devices` table and feed the same safety spine.

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | Detect connection and removal of USB removable storage volumes. | M |
| FR-1.2 | On connect, look for a registration file (`.loomis/device.json`) on the volume. | M |
| FR-1.3 | Register a new device **(explicit, user-initiated)**: persist a `devices` record and write `device.json` to the volume. | M |
| FR-1.4 | Capture per-device settings at registration: name, owner/speaker hint, auto-delete, transcode preference, audio path globs. | M |
| FR-1.5 | Recognize a previously registered device on reconnect via `device.json` (fallback: volume serial / label). | M |
| FR-1.6 | Validate and accept a hand-authored `device.json`. | S |
| FR-1.7 | Allow editing device settings later via the UI. | S |
| FR-1.8 | Support multiple registered devices. | S |
| FR-1.9 | Auto-backup and the processing pipeline run **only for registered devices**; an unregistered connected volume raises a prompt but is never imported automatically. | M |
| FR-1.10 | Unregister a device: remove its `device.json` (when reachable) and deactivate it so auto-backup stops. Imported recordings are retained. | S |
| FR-1.11 | Register a local **folder** as an ingest source (e.g. a phone-sync or lifelogger drop folder), with the same per-source settings as a device. | M |
| FR-1.12 | Poll registered folder sources for new audio and import it under the same ledger/safety spine as device backups. | M |
| FR-1.13 | Folder sources never delete source files by default; deletion is per-source opt-in exactly like devices (gated by FR-2.5). | M |

### FR-2 Backup & ingest
*Spec: [features/01](features/01-device-registration-and-backup.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | Enumerate audio files on a registered device using its globs. | M |
| FR-2.2 | Maintain a backup **ledger** so already-imported files are skipped (dedupe by content hash; path/size/mtime as fast pre-check). | M |
| FR-2.3 | Copy new files into a local staging area, then into the library. | M |
| FR-2.4 | **Verify every copy by SHA-256** before marking it backed up. | M |
| FR-2.5 | Optionally delete source files from the device **only after** a verified backup. | M |
| FR-2.6 | Resume cleanly after a mid-copy disconnect; never commit a partial file to the ledger. | M |
| FR-2.7 | Quarantine files whose copy fails verification and never delete their source. | M |
| FR-2.8 | Preserve original capture timestamps as recording metadata. | S |

### FR-3 Audio compression (optional)
*Spec: [features/02](features/02-audio-compression.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | Optionally transcode imported audio to Opus to save space. | M |
| FR-3.2 | Make bitrate/quality and the speech-optimized (`voip`) profile configurable. | S |
| FR-3.3 | Verify the transcode produced valid, decodable audio before deleting any original. | M |
| FR-3.4 | Allow per-device override of the global transcode policy. | S |

### FR-4 Transcription
*Spec: [features/03](features/03-transcription.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | Transcribe each recording to text with word-level timestamps. | M |
| FR-4.2 | Auto-detect language; support Mandarin and other languages. | M |
| FR-4.3 | Store the full transcript plus time-aligned segments. | M |
| FR-4.4 | Run STT through a swappable engine interface (default: WhisperX). | S |
| FR-4.5 | Auto-detect GPU and fall back to CPU; make model size configurable. | S |

### FR-5 Diarization & speaker identity
*Spec: [features/04](features/04-speaker-diarization-and-identification.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | Assign speaker turns within a recording (diarization). | M |
| FR-5.2 | Compute a voiceprint (embedding) per speaker turn/segment. | M |
| FR-5.3 | Match voiceprints against a persistent speaker database for cross-recording identities. | M |
| FR-5.4 | Create a provisional identity when no confident match exists. | M |
| FR-5.5 | Let the user name, confirm, correct, merge, and split speaker identities. | M |
| FR-5.6 | Use user corrections to improve future matching. | S |
| FR-5.7 | Support enrolling a known voice from a labeled sample. | C |
| FR-5.8 | Suggest display names for unnamed speakers from conversational evidence (being addressed by name, self-introductions) during summarization; suggestions become canonical only after user confirmation. | S |

### FR-6 Summarization & organization
*Spec: [features/05](features/05-summarization-and-organization.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | Classify each recording as *diary-type* or *meeting-type*. | M |
| FR-6.2 | Aggregate diary-type recordings **per calendar day** into one first-person diary entry. | M |
| FR-6.3 | Extract genuine multi-speaker discussions into standalone meeting records. | M |
| FR-6.4 | Link meetings from the corresponding day's diary entry. | M |
| FR-6.5 | Diary output: narrative, topics, mood, to-dos/decisions. | S |
| FR-6.6 | Meeting output: title, attendees, summary, decisions, action items with owners. | S |
| FR-6.7 | Store summaries as Markdown plus structured metadata. | M |
| FR-6.8 | Re-summarize idempotently when late clips arrive for a day. | S |
| FR-6.9 | Run the LLM through a swappable provider interface (default: Ollama; optional cloud). | M |

### FR-7 User interface
*Spec: [07 UI/UX Design](07-ui-ux-design.md), [11 API Specification](11-api-specification.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | Provide a local web UI (Vue SPA) talking to the backend over a REST/WebSocket API; the backup/processing daemon runs independently in the background. | M |
| FR-7.2 | Timeline/calendar of days with diary + meeting entries. | M |
| FR-7.3 | Recording detail: audio player + speaker-labeled transcript. | M |
| FR-7.4 | Speaker management screen (rename/confirm/merge/split). | M |
| FR-7.5 | Full-text search across transcripts, diaries, and meetings. | S |
| FR-7.6 | Jobs/health view with retry controls. | S |
| FR-7.7 | Settings: devices, defaults, models, cloud remotes. | M |
| FR-7.8 | Surface any pending network egress (cloud sync / cloud LLM) explicitly. | M |
| FR-7.9 | Expose a versioned local REST/WebSocket API (OpenAPI-documented) as the sole backend↔frontend contract; no business logic in the frontend. | M |

### FR-8 Cloud sync (optional)
*Spec: [features/06](features/06-cloud-sync.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-8.1 | Optionally back up the library to cloud storage (OneDrive + others) via rclone. | M |
| FR-8.2 | Configure remotes and select what to sync (audio, Markdown, DB backup). | S |
| FR-8.3 | Run on a schedule and/or on demand, with visible progress and logs. | S |
| FR-8.4 | Default to push-only; never delete local source data because of sync. | M |

### FR-9 Configuration & data management
*Spec: [06 Configuration](06-configuration.md), [05 Data Model](05-data-model-and-storage.md)*

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-9.1 | Single TOML config file with environment-variable overrides. | M |
| FR-9.2 | All app data under one configurable data directory. | M |
| FR-9.3 | Versioned, automatic database schema migrations. | M |
| FR-9.4 | Export/backup of the SQLite database. | S |

## 2. Non-functional requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | **Privacy** | Default configuration performs **no** network egress. Every networked feature is opt-in and visibly indicated. |
| NFR-2 | **Data integrity** | Destructive actions (source deletion) are gated by checksum verification. The pipeline is idempotent and resumable. |
| NFR-3 | **Reliability** | Crash/disconnect must not corrupt the library or DB; jobs resume from their last good step. |
| NFR-4 | **Portability** | Windows is the primary target; avoid OS-specific assumptions where reasonable so Linux/macOS stay feasible. |
| NFR-5 | **Performance** | Use GPU when available; degrade gracefully to CPU. Long jobs must not block the UI or device watcher. |
| NFR-6 | **Usability** | The happy path requires only plugging in the device. |
| NFR-7 | **Observability** | Structured logs; the UI shows queued/running/failed work with actionable errors. |
| NFR-8 | **Extensibility** | STT, LLM, and cloud backends sit behind interfaces and are swappable via config. |
| NFR-9 | **Security** | Cloud/LLM credentials stored outside the repo and out of logs; least-privilege scopes. |
| NFR-10 | **Maintainability** | Typed Python, linted/formatted, tested; single `pyproject.toml`. |
| NFR-11 | **Resource footprint** | Idle daemon is lightweight; heavy models load on demand and can unload. |

## 3. Out of scope (this release)

Real-time transcription; native mobile apps; multi-user/hosted SaaS; audio
editing; auto-joining live calls. See [01 §4](01-vision-and-scope.md#4-non-goals-v1).

## 4. Open questions

Tracked in the [roadmap](08-roadmap-and-milestones.md) and individual
[ADRs](adr/README.md). Notable: speaker-merge UX, diary "day-settled" debounce,
contiguous-recording grouping for meetings.
