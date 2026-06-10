# 06 · Feature — Cloud Sync

| | |
|---|---|
| **Document** | Feature Spec — Cloud Sync |
| **Doc ID** | LM-F06 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [02 Flows §7](../02-user-flows.md#7-cloud-sync-optional), [06 Configuration](../06-configuration.md), [09 Security](../09-security-and-privacy-model.md), [ADR-0004](../adr/0004-cloud-backup-rclone.md) |
| **Traces** | FR-8.1 … FR-8.4 |

---

## 1. Overview

**Optional**, opt-in off-machine backup of the library to OneDrive and other
cloud providers. Disabled by default; nothing leaves the machine until
`[cloud].enabled = true`.

## 2. Backend (FR-8.1)

**rclone** behind a `CloudSync` interface
([ADR-0004](../adr/0004-cloud-backup-rclone.md)): one integration covers 70+
providers (OneDrive, Google Drive, Dropbox, S3, …) with checksum-verified,
resumable transfers. Loomis shells out to the rclone binary; remotes are
configured via rclone's own tooling and referenced by name in `[cloud.remotes]`.

## 3. Scope & direction (FR-8.2, FR-8.4)

Per remote (`[[cloud.remotes]]`), select what to push and where:

| Scope | Pushes | Remote path |
|-------|--------|-------------|
| `audio` | `library/` | `<name>:<dest>/library` |
| `markdown` | `diary/`, `meetings/` | `<name>:<dest>/diary`, `…/meetings` |
| `db` | a consistent DB snapshot (`VACUUM INTO`; the live WAL file is never copied raw) | `<name>:<dest>/db/loomis.db` |

Direction is **push-only and mechanically so**: the wrapper only ever issues
`rclone copy`, which cannot delete on either side; `rclone sync` (which mirrors
deletions) is deliberately not exposed. Sync **never deletes local source
data** (FR-8.4).

## 4. Triggering (FR-8.3)

Manual "sync now" — `POST /cloud/sync` (optionally `{"remote": "<name>"}`) —
enqueues a durable `cloud_sync` job, so it retries like any pipeline step and
streams `job.updated` / `cloud.synced` over the WebSocket. Each remote's run
writes a `cloud_sync_log` row
([05 §4.14](../05-data-model-and-storage.md#414-cloud_sync_log)), listed at
`GET /cloud/log` and shown on the Sources screen. The cron schedule
(`[cloud].schedule_cron`) is consumed by the daemon Scheduler (separate M5
work). The handler re-checks `[cloud].enabled` at execution time — a job
enqueued before the user disables sync is refused, never run (NFR-1).

## 5. Privacy & credentials

Enabling cloud sync crosses the trust boundary
([04 §10](../04-system-architecture.md#10-privacy--trust-boundary)); the UI
surfaces this ([FR-7.8](../03-requirements-specification.md#fr-7-user-interface)).
Including `db`/voiceprints in scope uploads biometric-adjacent data — called out
explicitly in [09 Security & Privacy](../09-security-and-privacy-model.md).
Credentials live in rclone's config, never in Loomis's repo or logs.

## 6. Alternatives & future

Native `msgraph-sdk` (OneDrive-only, no external binary) could be added behind
the same interface later — see
[ADR-0004 alternatives](../adr/0004-cloud-backup-rclone.md#alternatives-considered).

## 7. Open questions

- Conflict policy if the same library is synced from two machines.
- Whether to encrypt-at-rest before upload (rclone `crypt` remote) by default for
  the `db`/voiceprints scope.
