# 08 · Roadmap & Milestones

| | |
|---|---|
| **Document** | Roadmap & Milestones |
| **Doc ID** | LM-08 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-09 |
| **Related** | [03 SRS](03-requirements-specification.md), [features/](features/) |
| **Traces** | All FRs (sequenced) |

---

Milestones staged by **completeness**, not by feature. Each milestone is a
maturity gate: it moves the whole product from one usable level to the next, and
bundles whatever features that level requires. A milestone is "done" only when
its **exit criteria** hold. IDs reference [03 SRS](03-requirements-specification.md).
A plan, not a promise.

## M0 — Foundation ✅
Design docs, ADRs, and OSS project files. The plan is the contract; no
application code yet.
> **Exit:** design stable enough to build against. **Met.**

## M1 — Safe ingest ✅
*The device-to-transcript spine works, headless and durable. Audio is captured
without data loss and every recording becomes a transcript on disk.*
[features/01](features/01-device-registration-and-backup.md),
[features/02](features/02-audio-compression.md),
[features/03](features/03-transcription.md)

- ✅ Device detection + registration, `device.json` validate — FR-1.1–1.5
- ✅ Backup ledger, copy, **SHA-256 verify**, quarantine, gated source delete — FR-2.1–2.7
- ✅ SQLite schema + migrations, config loading — FR-9.1–9.3
- ✅ Durable job queue + worker pool (atomic claim, retry/park, crash-reclaim) — 04 §7
- ✅ Swappable `STTEngine` (WhisperX; `null` for offline/CI), transcript persistence — FR-4.1–4.5
- ✅ Optional Opus transcode + validation, gated source delete — FR-3.1–3.4
- ✅ CLI: `loomis backup …`, `loomis worker …`
> **Exit:** no data-loss path; pipeline idempotent & crash-resumable through
> `stt`. **Met.** Native USB events (WMI/pyudev) remain a later poll optimisation.

## M2 — Local intelligence (Alpha, headless)
*The pipeline runs end-to-end. Plug in a device and the library fills itself with
who-said-what and daily diaries + meetings — all local, CLI-driven, no UI yet.*
[features/04](features/04-speaker-diarization-and-identification.md),
[features/05](features/05-summarization-and-organization.md)

- pyannote diarization, voiceprint embeddings, matching/enrollment, provisional identities — FR-5.1–5.4, 5.7
- LLM adapter (Ollama default) + structured output — FR-6.9
- Diary vs meeting classification — FR-6.1
- Daily diary aggregation — FR-6.2, 6.5, 6.8
- Meeting extraction + diary linking — FR-6.3, 6.4, 6.6
- Markdown + metadata output — FR-6.7
> **Exit:** a recording flows `import → … → {diary|meeting} → link` unattended;
> a real, browsable-on-disk lifelog exists without a UI.

## M3 — Browsable product (Beta)
*The lifelog becomes something you actually open and use daily.*
[07 UI/UX](07-ui-ux-design.md), [11 API](11-api-specification.md)

- **Backend:** FastAPI REST/WebSocket surface + OpenAPI — FR-7.9
- **Frontend:** Vue 3 + Vuetify SPA (Vite, Pinia, generated API client) in `web/` — FR-7.1
- Timeline, recording detail, transcript player — FR-7.2/7.3
- Speaker management — FR-7.4, FR-5.5/5.6
- Full-text search (FTS5) — FR-7.5 · live jobs/health over WebSocket — FR-7.6
- Settings + egress indicators — FR-7.7/7.8
> **Exit:** a non-CLI user can browse, search, and manage the lifelog start to finish.

## M4 — Release 1.0
*Trustworthy, installable, and optionally backed up off-machine.*
[features/06](features/06-cloud-sync.md)

- Opt-in cloud sync: rclone wrapper + remote config, scheduled/manual push, push-only safety — FR-8.1–8.4
- Packaging / run-as-service on Windows; first-run setup
- Test coverage on the integrity spine and pipeline resume
- Docs polish, example data, `CHANGELOG` 0.1.0
> **Exit:** clean install on a fresh machine; integrity spine covered by tests;
> off-machine backup available without breaking local-first defaults.

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
