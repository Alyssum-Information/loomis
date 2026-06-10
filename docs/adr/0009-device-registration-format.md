# 0009 — Device registration: `.loomis/device.json`

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Feature #1 wants Loomis to **create a file on the recording device** to register
it and enable later identification/management. We need to recognize a specific
recorder across reconnects (and even across computers), and carry per-device
preferences (auto-delete, transcode policy, audio locations).

Volume serials/labels alone are unreliable identifiers (collisions, reformatting,
OS differences), so an on-device marker is preferable when the device is
writable.

## Decision

Write a small JSON file at **`<volume>/.loomis/device.json`** at registration.
It carries a stable Loomis-generated `device_id` (UUID), a human name, an owner
voice hint, audio globs, and per-device backup/transcode preferences. It is
**versioned** via a `schema` field and validated (pydantic) on every connect.
Full schema in [05 §2](../05-data-model-and-storage.md#2-on-source-registration-file--devicejson).
[ADR-0012](0012-folder-sources.md) later extends the same file (with a `kind`
field) to watched-folder sources.

Identity resolution order: `device_id` from `device.json` → volume serial/label
fallback (when the file is missing or the volume is read-only).

## Alternatives considered

- **JSON** (chosen) — human-readable, ubiquitous, trivial to hand-author/inspect,
  matches the user's suggestion.
- **TOML/YAML on device** — fine too, but JSON needs no extra parser assumptions
  and is the most portable for a tiny machine-written marker.
- **Identify by volume serial only (no file)** — rejected as primary: unreliable
  and can't carry preferences; kept only as a fallback.
- **Hidden binary/sqlite marker on device** — rejected: not inspectable;
  overkill for a few fields.

## Consequences

- **Pros:** portable recognition across machines; self-describing; carries
  per-device policy; easy to inspect/edit; forward-compatible via `schema`.
- **Cons:** requires a writable device (handled by DB-only fallback); a user
  could delete/modify it — validation + serial fallback mitigate this.
- The `.loomis/` directory keeps the marker tidy and namespaced on the device.
