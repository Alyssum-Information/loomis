# 06 · Feature — Cloud Sync

| | |
|---|---|
| **Document** | Feature Spec — Cloud Sync |
| **Doc ID** | LM-F06 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
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

Per remote, select what to sync — `audio` / `markdown` / `db` — and the
direction. Default is **push-only**; sync **never deletes local source data**.
Remote-side deletion behaviour is opt-in and clearly labeled.

## 4. Scheduling (FR-8.3)

Manual "sync now" (a `ui_intent`) and/or a schedule
(`[cloud].schedule_cron`). The Scheduler in the daemon
([04 §3.1](../04-system-architecture.md#31-daemon-background-workers))
runs rclone, surfaces progress, and writes a `cloud_sync_log` row
([05 §4.14](../05-data-model-and-storage.md#414-cloud_sync_log)).

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
