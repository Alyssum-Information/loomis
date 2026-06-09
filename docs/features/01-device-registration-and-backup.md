# 01 · Feature — Device Registration & Backup

| | |
|---|---|
| **Document** | Feature Spec — Device Registration & Backup |
| **Doc ID** | LM-F01 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [02 Flows §1–2](../02-user-flows.md), [05 Data Model](../05-data-model-and-storage.md), [02 Audio Compression](02-audio-compression.md), [ADR-0009](../adr/0009-device-registration-format.md), [ADR-0011](../adr/0011-usb-device-detection.md) |
| **Traces** | FR-1.1 … FR-1.10, FR-2.1 … FR-2.8 |

---

## 1. Overview

This is the entry point of the whole product: detect the recorder, recognize it,
and import its recordings **without ever losing source audio**. It owns the
data-integrity "safety spine"
([04 §8](../04-system-architecture.md#8-data-integrity-the-safety-spine)).

## 2. Device detection (FR-1.1)

A `DeviceWatcher` interface with platform adapters
([ADR-0011](../adr/0011-usb-device-detection.md)):

- **Baseline (all OS):** poll removable volumes via **psutil** every
  `backup.poll_interval_s` and diff the set → `device_connected` /
  `device_removed` events.
- **Native events (optional):** Windows WMI / `WM_DEVICECHANGE`; Linux pyudev —
  for instant, low-overhead notification.

## 3. Registration (FR-1.2 … FR-1.6, FR-1.9)

Registration is **explicit and opt-in**. Connecting a volume never registers or
imports it on its own — the user decides which volumes are recorders.

1. On connect, look for `<volume>/.loomis/device.json`.
2. **Registered device** (file present → a `devices` row resolved by `device_id`,
   or a serial/label match for a read-only volume) → go to §4 (auto-backup).
3. **Unregistered volume** → emit a `device.connected` event flagged
   `registered: false`; the UI raises a prompt (it also appears in the Devices
   screen's *pending* list). **No import happens.** Nothing is written to the
   volume and no `devices` row is created.
4. **Register** (user action — the Devices screen, or the `loomis backup` CLI which
   targets a volume explicitly): write `device.json` to the volume **and** insert
   (or re-activate) the `devices` row with `registered = 1`.
5. **Fallbacks:** hand-authored `device.json` is validated and accepted (FR-1.6);
   read-only volume → DB-only registration, identity falls back to volume serial
   / label (FR-1.5).

`device.json` schema and the `devices` table:
[05 §2](../05-data-model-and-storage.md#2-on-device-registration-file--devicejson),
[05 §4.1](../05-data-model-and-storage.md#41-devices). Multiple devices are
supported (FR-1.8); settings are editable later via the UI (FR-1.7).

### 3.1 Unregister (FR-1.10)

The user can unregister a device from the Devices screen. This removes its
`device.json` (when the volume is connected) and deactivates the `devices` row
(`registered = 0`) so auto-backup stops. **Imported recordings are retained** —
the `devices` row is kept (recordings reference it), just marked inactive; a later
re-registration reactivates it.

## 4. Backup & ingest (FR-2.1 … FR-2.8)

Runs **only for registered devices** (FR-1.9). The ordered, integrity-preserving
import:

| # | Step | Guarantee |
|---|------|-----------|
| 1 | Enumerate audio by the device's globs (FR-2.1) | — |
| 2 | Dedupe against the **ledger** `recordings` (FR-2.2): fast pre-check on path+size+mtime, authoritative on SHA-256 | already-imported files skipped |
| 3 | Copy new file → `staging/` (FR-2.3) | original untouched |
| 4 | **Verify** copy by SHA-256 (FR-2.4) ⚠️ | mismatch → `quarantine/`, never deleted (FR-2.7) |
| 5 | Commit to `library/` + ledger row | atomic "backed up" point |
| 6 | (Optional) transcode + validate → [08](02-audio-compression.md) | |
| 7 | (Optional, FR-2.5) delete source ⚠️ | **only after** steps 4–6 succeed |
| 8 | Enqueue processing job → [04 §6](../04-system-architecture.md#6-processing-pipeline) | |

Capture timestamps are preserved as `recordings.recorded_at` (FR-2.8).

## 5. Source cleanup policy (FR-2.5)

Off by default. When on (global or per-device), deletion is strictly gated by a
verified backup — see the safety spine. Disconnect mid-copy leaves nothing
half-committed; the ledger makes reconnect resume idempotently
([02 §8](../02-user-flows.md#8-device-removed--reconnected)).

## 6. Failure handling

| Situation | Behaviour |
|-----------|-----------|
| Device removed mid-copy | partial staging file discarded; not committed; resume next connect |
| Hash mismatch | file → `quarantine/`; source never deleted; surfaced in UI |
| Read-only / full device | DB-only registration; warn; serial/label fallback |
| Duplicate re-import | `(device_id, sha256)` UNIQUE → no-op |

## 7. Open questions

- ~~Heuristic for `recorded_at` when the device provides no reliable metadata.~~
  **Decided (M1):** fall back to the source file's mtime; richer container/metadata
  probing is deferred to transcription (also M1), which already opens each file.
- Whether to detect device-side file *moves/renames* vs treat as new (hash dedupe
  already covers content identity).
