# 10 · Glossary

| | |
|---|---|
| **Document** | Glossary |
| **Doc ID** | LM-10 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | all docs |
| **Traces** | — |

---

| Term | Definition |
|------|------------|
| **Backup ledger** | The `recordings` table used to dedupe imports by content hash so already-backed-up files are skipped. [05 §4.2](05-data-model-and-storage.md#42-recordings--the-backup-ledger--pipeline-source-of-truth) |
| **Daemon** | The headless background process that does all side effects (watch, import, process, sync). [04 §3.1](04-system-architecture.md#31-daemon-background-workers) |
| **Backend / Frontend** | `backend/` = Python (core, pipeline, daemon, FastAPI API); `web/` = Vue 3 + Vuetify SPA. Split per [ADR-0003](adr/0003-frontend-vue-spa.md). [04 §12](04-system-architecture.md#12-repository-layout) |
| **REST/WebSocket API** | The local FastAPI surface the SPA consumes; REST for queries/commands, WebSocket for live job/health/egress push. [11](11-api-specification.md) |
| **SPA** | The Vue + Vuetify single-page app in `web/`; pure client, no business logic, never touches SQLite/library. [07](07-ui-ux-design.md) |
| **Day-settled debounce** | Timer that decides a calendar day looks complete before its diary is summarized; re-opens on late clips. [features/05 §3](features/05-summarization-and-organization.md#3-diary-mode-fr-62-fr-65-fr-68) |
| **device.json** | The `.loomis/device.json` registration file written to a source's root (recorder volume or watched folder). [05 §2](05-data-model-and-storage.md#2-on-source-registration-file--devicejson) |
| **Diarization** | Segmenting a recording into speaker turns (who spoke when), within one file. [features/04](features/04-speaker-diarization-and-identification.md) |
| **Diary-type / Meeting-type** | Classification of a recording that routes it to daily diary aggregation vs a standalone meeting record. [features/05 §2](features/05-summarization-and-organization.md#2-classification-fr-61) |
| **Egress / Trust boundary** | Any point where data leaves the local machine; nothing crosses it by default. [04 §10](04-system-architecture.md#10-privacy--trust-boundary) |
| **Job step** | A retryable, idempotent unit of pipeline work persisted in the `jobs` queue. [04 §6–7](04-system-architecture.md#6-processing-pipeline) |
| **Library** | The local filesystem store of imported audio + generated Markdown. [05 §1](05-data-model-and-storage.md#1-on-disk-layout) |
| **Local-first** | Default behaviour uses only local resources (SQLite, local STT, Ollama) and makes no network calls. [01 §3](01-vision-and-scope.md#3-goals) |
| **Owner / owner_speaker_hint** | The primary voice associated with a device, used as a prior in speaker ID and as the diary's first-person voice. |
| **Opus** | The audio codec used for optional high-compression archiving. [features/02](features/02-audio-compression.md) |
| **Provisional identity** | An auto-created speaker not yet confirmed by the user. [features/04 §5](features/04-speaker-diarization-and-identification.md#5-matching-algorithm-fr-53-fr-54) |
| **Quarantine** | Holding area for copies that failed SHA-256 verification; their source is never deleted. [features/01 §6](features/01-device-registration-and-backup.md#6-failure-handling) |
| **Safety spine** | The fixed ordering (copy → verify → commit → transcode-verify → delete) that prevents source-audio loss. [04 §8](04-system-architecture.md#8-data-integrity-the-safety-spine) |
| **Source** | Anywhere recordings arrive from: a USB recorder volume (`kind = usb`) or a watched folder (`kind = folder`, e.g. a phone-sync target). Both register into `devices`. [ADR-0012](adr/0012-folder-sources.md) |
| **Suggested name** | An LLM-proposed display name for an unnamed speaker, inferred from conversational evidence; becomes canonical only after user confirmation (FR-5.8). [features/04 §6.1](features/04-speaker-diarization-and-identification.md#61-llm-name-suggestions-fr-58) |
| **Speaker identification** | Matching a voiceprint to a stable identity *across* recordings. [features/04](features/04-speaker-diarization-and-identification.md) |
| **ui_intent** | A user action recorded by the UI for the daemon to execute, decoupling the two. [05 §4.16](05-data-model-and-storage.md#416-ui_intents) |
| **Voiceprint** | An L2-normalized speaker embedding stored for cosine-similarity identity matching. [features/04 §4](features/04-speaker-diarization-and-identification.md#4-voiceprints-fr-52) |
| **WhisperX** | The default speech-to-text engine (word timestamps + integrated diarization). [features/03](features/03-transcription.md), [ADR-0002](adr/0002-stt-engine-whisperx.md) |
