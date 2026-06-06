# 09 · Security & Privacy Model

| | |
|---|---|
| **Document** | Security & Privacy Model |
| **Doc ID** | LM-09 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [04 §10 Trust boundary](04-system-architecture.md#10-privacy--trust-boundary), [06 Configuration](06-configuration.md), [features/06 Cloud Sync](features/06-cloud-sync.md), [ADR-0004](adr/0004-cloud-backup-rclone.md), [ADR-0005](adr/0005-llm-provider-abstraction.md) |
| **Traces** | NFR-1, NFR-9, FR-7.8, FR-2.4/2.5 |

---

This document is the canonical security & privacy model, including the
vulnerability-reporting policy (§7).

## 1. Data sensitivity

Loomis handles private voice recordings, their transcripts, and **voiceprints**
(biometric-adjacent speaker embeddings). All are treated as sensitive by default.

## 2. Privacy model (NFR-1)

- **Local-first by default.** In its default configuration Loomis makes **no**
  network connections. Audio, transcripts, summaries, the database, and
  voiceprints stay on the user's machine.
- **Opt-in egress only.** The only ways data leaves the machine:
  1. **Cloud sync** (rclone) — disabled by default
     ([features/06](features/06-cloud-sync.md), [ADR-0004](adr/0004-cloud-backup-rclone.md)).
  2. **Cloud LLM** — Ollama (local) is default; cloud providers opt-in
     ([ADR-0005](adr/0005-llm-provider-abstraction.md)).
- **Egress is visible** (FR-7.8): the UI flags any action/setting that will cross
  the trust boundary, including binding the UI to `0.0.0.0`. See
  [07 §4](07-ui-ux-design.md#4-egress-transparency-fr-78-).

## 3. Trust boundary

The only boundary is the user's own machine
([04 §10](04-system-architecture.md#10-privacy--trust-boundary)). Exposing the
backend API on the LAN (`[api].host = "0.0.0.0"`, which also requires a bearer
token — [11 §2](11-api-specification.md#2-auth--trust-boundary)) widens it and is
the user's explicit choice; treat it accordingly.

## 4. Voiceprints

Biometric-adjacent. Stored locally like all other data; never uploaded unless the
user explicitly includes the database in a cloud sync scope. Including `db`/
voiceprints in a sync scope is called out in the UI; encrypt-before-upload
(rclone `crypt`) is a tracked option
([features/06 §7](features/06-cloud-sync.md#7-open-questions)).

## 5. Credentials (NFR-9)

- Cloud LLM API keys → **environment variables only**; never in `config.toml`,
  never logged.
- Cloud storage credentials → **rclone's own config**, managed by the user,
  outside this repository.
- No secrets committed to the repo.

## 6. Data integrity as a security property (NFR-2)

Loomis must never lose source audio. Source deletion is opt-in and only follows a
**SHA-256-verified** backup (and validated transcode, if enabled). This is the
safety spine in
[04 §8](04-system-architecture.md#8-data-integrity-the-safety-spine) and
[features/01 §4](features/01-device-registration-and-backup.md#4-backup--ingest-fr-21--fr-28).

## 7. Vulnerability reporting

Loomis is pre-alpha. For exploitable issues, do **not** open a public issue;
report privately via the repository's security advisory feature or to the
maintainer, with reproduction steps and impact. Coordinated disclosure
appreciated.
