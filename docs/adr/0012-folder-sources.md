# 0012 — Watched folders as first-class ingest sources

- **Status:** Accepted
- **Date:** 2026-06-10

## Context

The original design assumed recordings arrive on **USB removable volumes**
([ADR-0011](0011-usb-device-detection.md)). In practice many capture devices
never mount as a drive: phones sync recordings into a local folder (Syncthing,
OneDrive, iCloud Drive), wearable lifeloggers export through a companion app,
and users drop files into a folder by hand. Forcing those through a fake
"volume" or manual CLI imports breaks the zero-friction goal
([01 §3](../01-vision-and-scope.md#3-goals)).

The question: how should non-volume sources enter the safety spine?

## Decision

Treat a **local folder** as a registered source of the same shape as a USB
device:

- One `devices` table for both, with `kind = "usb" | "folder"` and
  `source_path` holding the folder's absolute path. Registration writes the
  same `.loomis/device.json` contract ([ADR-0009](0009-device-registration-format.md))
  into the folder root, so a moved/re-synced folder is still recognized.
- The **daemon polls** registered folders on `[backup].folder_poll_interval_s`
  (default 60 s) and runs the unchanged backup path (ledger dedupe, SHA-256
  verify, quarantine). No new import machinery.
- **Settle window:** a file is imported only after its mtime has been stable
  for `[backup].folder_settle_seconds` (default 10 s), so files still being
  written by a sync tool are never half-imported.
- **No deletion by default** (FR-1.13): sync tools own their folders; deleting
  from them can propagate back to the phone. `auto_delete` stays per-source
  opt-in and remains gated by the verified-backup rule (FR-2.5).

## Alternatives considered

- **Separate `folder_sources` table / parallel pipeline** — duplicates the
  registration model, settings, and UI for no benefit; recordings need the same
  ledger and jobs either way.
- **Filesystem-event watching (watchdog/inotify/ReadDirectoryChangesW)** —
  lower latency, but sync tools fire storms of partial-write events and the
  settle window would still be needed; polling at a relaxed interval is
  simpler, portable, and plenty fast for batch audio.
- **Importing in place (no copy)** — leaves the library's integrity hostage to
  the sync tool (it may rewrite, move, or delete files); copying through the
  safety spine keeps "never lose source audio" intact.

## Consequences

- Phones and lifeloggers work today with any sync tool the user already runs;
  Loomis itself still makes **no network connections** (the sync tool does, on
  the user's terms — outside Loomis's trust boundary).
- The Devices screen lists both kinds; folder sources show their path and a
  *watched* state instead of *connected*.
- The poll loop adds a cheap periodic stat-scan per folder; the existing
  path+size+mtime pre-check keeps repeat polls O(files) with no hashing.
