# Architecture Decision Records

ADRs capture **why** a significant choice was made, the alternatives weighed, and
the consequences — so future contributors (and future us) don't re-litigate
settled questions without new information. Format follows
[Michael Nygard's ADR template](https://github.com/joelparkerhenderson/architecture-decision-record).

Each ADR has a status: `Proposed` · `Accepted` · `Superseded` · `Deprecated`.
ADRs are immutable once accepted; to change a decision, add a new ADR that
supersedes the old one.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-stt-engine-whisperx.md) | Speech-to-text engine: WhisperX | Accepted |
| [0003](0003-frontend-vue-spa.md) | Frontend: Vue + Vuetify SPA over FastAPI | Accepted |
| [0004](0004-cloud-backup-rclone.md) | Cloud backup backend: rclone | Accepted |
| [0005](0005-llm-provider-abstraction.md) | LLM provider abstraction, Ollama default | Accepted |
| [0006](0006-database-sqlite.md) | Database: SQLite | Accepted |
| [0007](0007-speaker-diarization-pyannote.md) | Diarization & voiceprints: pyannote | Accepted |
| [0008](0008-audio-compression-opus.md) | Audio compression: Opus | Accepted |
| [0009](0009-device-registration-format.md) | Device registration: `.loomis/device.json` | Accepted |
| [0010](0010-python-tooling.md) | Python tooling: uv + ruff + mypy | Accepted |
| [0011](0011-usb-device-detection.md) | USB detection: poll + native events | Accepted |

> Decisions reflect the ecosystem as surveyed in **June 2026**; STT/LLM tooling
> moves fast, so revisit the model/engine choices periodically.
