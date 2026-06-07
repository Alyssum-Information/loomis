# 0011 — USB detection: poll + native events

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

The whole experience is triggered by **plugging in the recorder**, so detecting
removable-volume connect/removal is foundational
([FR-1.1](../03-requirements-specification.md#fr-1-device-detection--registration)). The primary
platform is **Windows 11**, with Linux/macOS as future targets. There is no
single clean cross-platform API:

- **Linux:** `pyudev` gives real udev add/remove events.
- **Windows:** no `pyudev`; options are WMI volume-change events
  (`Win32_VolumeChangeEvent`) / `WM_DEVICECHANGE` window messages, or simply
  **polling** the set of removable drives.
- **psutil** lists mounted partitions cross-platform (good for diffing drive sets
  by polling).

## Decision

Implement a `DeviceWatcher` interface with **platform adapters**:

- **Baseline (all platforms):** poll removable volumes via **psutil** on a short
  interval (default 3 s) and diff the set to detect connect/removal. Simple,
  portable, dependency-light.
- **Native events where cheap:** on Windows, optionally use WMI/`WM_DEVICECHANGE`
  for prompt, low-overhead notifications; on Linux, optionally use **pyudev**.

The watcher emits normalized `device_connected` / `device_removed` events the
rest of the system consumes; the daemon resolves each volume against the device
registry ([ADR-0009](0009-device-registration-format.md)).

## Alternatives considered

- **Polling only** — simplest; chosen as the always-available baseline. Slight
  latency/CPU cost, acceptable at a few-second cadence.
- **Native events only** — lowest latency, but per-OS complexity and no single
  abstraction; used as an *enhancement*, not the baseline.
- **`watchdog`** (filesystem watcher) — watches file changes, not volume
  arrival/removal; wrong tool for "device plugged in."

## Consequences

- **Pros:** works on day one everywhere via polling; upgradable to instant native
  events per OS; clean abstraction isolates platform code.
- **Cons:** polling adds minor latency and periodic wakeups; native-event paths
  add per-platform code to maintain (optional, behind the interface).
- Mid-operation removal is handled by the integrity model — partial copies are
  never committed ([04 §8](../04-system-architecture.md#8-data-integrity-the-safety-spine)).

## References

- psutil — https://github.com/giampaolo/psutil
- pyudev — https://pyudev.readthedocs.io
- "Detecting USB drive insertion & removal on Windows using Python" — abdus.dev
