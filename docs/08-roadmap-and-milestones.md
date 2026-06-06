# 08 · Roadmap & Milestones

| | |
|---|---|
| **Document** | Roadmap & Milestones |
| **Doc ID** | LM-08 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [03 SRS](03-requirements-specification.md), [features/](features/) |
| **Traces** | All FRs (sequenced) |

---

Milestone-based, value-first ordering. Each milestone is independently useful.
IDs reference [03 SRS](03-requirements-specification.md). A plan, not a promise.

## M0 — Project scaffold ✅ (this stage)
Design docs, ADRs, and OSS project files. No application code yet.

## M1 — Backup core (the safety spine)
*Goal: plug in a device and reliably, safely import audio.*
[features/01](features/01-device-registration-and-backup.md)
- Device detection + registration — FR-1.1–1.5
- `device.json` read/write/validate — FR-1.2/1.3
- Backup ledger, copy, **SHA-256 verify** — FR-2.1–2.4, 2.6, 2.7
- Optional source deletion gated on verification — FR-2.5
- SQLite schema + migrations — FR-9.2/9.3 · Config loading — FR-9.1
- Minimal CLI to run a backup
> Exit: no data-loss path; re-import idempotent.

## M2 — Transcription & transcripts
*Goal: every imported recording becomes a searchable transcript.*
[features/02](features/02-audio-compression.md), [features/03](features/03-transcription.md)
- Durable job queue + worker pool
- WhisperX integration, GPU/CPU auto — FR-4.1–4.5
- Transcript + segment persistence
- Optional Opus transcode + validation — FR-3.1–3.4

## M3 — Speakers
*Goal: know who spoke, across recordings.*
[features/04](features/04-speaker-diarization-and-identification.md)
- pyannote diarization — FR-5.1
- Voiceprint embeddings + matching/enrollment — FR-5.2–5.4, 5.7
- Provisional identities — FR-5.4

## M4 — Summaries & organization
*Goal: diaries and meetings, automatically.*
[features/05](features/05-summarization-and-organization.md)
- Diary vs meeting classification — FR-6.1
- LLM adapter (Ollama default) + structured output — FR-6.9
- Daily diary aggregation — FR-6.2, 6.5, 6.8
- Meeting extraction + diary linking — FR-6.3, 6.4, 6.6
- Markdown + metadata output — FR-6.7

## M5 — API + Web UI
*Goal: a lifelog you want to browse.* [07 UI/UX](07-ui-ux-design.md), [11 API](11-api-specification.md)
- **Backend:** FastAPI REST/WebSocket surface + OpenAPI — FR-7.9
- **Frontend:** Vue 3 + Vuetify SPA scaffold (Vite, Pinia, generated API client) in `web/` — FR-7.1
- Timeline, recording detail, transcript player — FR-7.2/7.3
- Speaker management — FR-7.4, FR-5.5/5.6
- Full-text search (FTS5) — FR-7.5 · Jobs/health (live over WebSocket) — FR-7.6
- Settings + egress indicators — FR-7.7/7.8

## M6 — Cloud sync (opt-in)
*Goal: your own off-machine backup.* [features/06](features/06-cloud-sync.md)
- rclone wrapper + remote config — FR-8.1/8.2
- Scheduled/manual push with progress — FR-8.3
- Push-only safety guarantees — FR-8.4

## M7 — Hardening & release
- Packaging/run-as-service on Windows; first-run setup
- Test coverage on the integrity spine and pipeline resume
- Docs polish, example data, `CHANGELOG` 0.1.0

## Backlog / ideas (unscheduled)
- Weekly/monthly diary roll-ups
- Native cloud-provider LLM/cloud adapters beyond rclone
- Contiguous-clip meeting grouping heuristics
- Desktop system-tray shell around the web UI
- Linux/macOS first-class support
- Sentiment/topic analytics over the lifelog
- Auto-generated TypeScript API client published as a package; API token UX for LAN mode

## Tracked open questions
- Speaker merge/split UX details — FR-5.5
- Diary "day-settled" debounce policy — [features/05](features/05-summarization-and-organization.md)
- Meeting grouping rule — [features/05](features/05-summarization-and-organization.md)
- Vector search backend switch point (memory → sqlite-vec) — [ADR-0007](adr/0007-speaker-diarization-pyannote.md)
