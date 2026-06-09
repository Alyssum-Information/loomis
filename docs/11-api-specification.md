# 11 · API Specification

| | |
|---|---|
| **Document** | API Specification (backend ↔ frontend) |
| **Doc ID** | LM-11 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-07 |
| **Related** | [04 Architecture](04-system-architecture.md), [05 Data Model](05-data-model-and-storage.md), [07 UI/UX](07-ui-ux-design.md), [09 Security](09-security-and-privacy-model.md), [ADR-0003](adr/0003-frontend-vue-spa.md) |
| **Traces** | FR-7.1 … FR-7.8 (frontend↔backend contract) |

---

The Vue SPA ([`web/`](../README.md)) talks to the Python backend
([`backend/`](04-system-architecture.md#12-repository-layout)) **only** over this
local API. REST for queries/commands; a WebSocket for live push. This document is
the design-level contract; the implementation is the source of truth and
auto-publishes an **OpenAPI** schema (FastAPI) from which the frontend generates
a typed client.

## 1. Conventions

- **Base URL:** `http://127.0.0.1:8080/api/v1` (host/port per
  [06 Configuration](06-configuration.md); `/api` versioned with `v1`).
- **Format:** JSON; `snake_case` fields mirroring [05 Data Model](05-data-model-and-storage.md).
- **Validation:** request/response bodies are pydantic models (shared with the
  backend), surfaced in OpenAPI.
- **Errors:** standard HTTP status + `{ "error": { "code", "message", "details?" } }`.
- **Pagination:** list endpoints take `?limit=&cursor=` and return
  `{ "items": [...], "next_cursor": null }`.
- **Long work is never synchronous:** command endpoints validate, enqueue a job,
  and return `202 Accepted` with a `job_id`; progress arrives over the WebSocket.

## 2. Auth & trust boundary

- Default bind `127.0.0.1` (single-user, same machine) — no auth required by
  default.
- Binding to the LAN (`[api].host = "0.0.0.0"`) is opt-in and, when enabled,
  **requires a local API token** (sent as `Authorization: Bearer <token>`) and
  is flagged in the UI. CORS allows only the configured frontend origin (the
  Vite dev origin in development). See
  [09 Security & Privacy](09-security-and-privacy-model.md).

## 3. REST resources (v1)

### 3.1 Devices
| Method | Path | Purpose | Traces |
|--------|------|---------|--------|
| GET | `/devices` | list registered devices + `last_seen` | FR-1.5/1.8 |
| GET | `/devices/{id}` | device detail | — |
| POST | `/devices/register` | register (or re-activate) a connected volume (name, owner hint, policies) — explicit, user-initiated | FR-1.3/1.4 |
| DELETE | `/devices/{id}` | unregister: remove `device.json` (when reachable) + deactivate; recordings retained | FR-1.10 |
| PATCH | `/devices/{id}` | edit device settings | FR-1.7 |
| GET | `/devices/pending` | connected volumes that are **not registered** (drives the prompt); only registered devices auto-import | FR-1.2/1.9 |

### 3.2 Recordings & transcripts
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/recordings` | list/filter (by device, date, status) |
| GET | `/recordings/{id}` | recording detail + status |
| GET | `/recordings/{id}/transcript` | segments (speaker-labeled, timestamped) |
| GET | `/recordings/{id}/audio` | stream audio (range requests) for the player |

### 3.3 Timeline, diary & meetings
| Method | Path | Purpose | Traces |
|--------|------|---------|--------|
| GET | `/timeline?from=&to=` | days with diary + meeting chips | FR-7.2 |
| GET | `/diary/{date}` | a day's diary entry (Markdown + metadata) | FR-6.2 |
| POST | `/diary/{date}/resummarize` | re-run aggregation (→ job) | FR-6.8 |
| GET | `/meetings/{id}` | meeting record | FR-6.3 |

### 3.4 Speakers (FR-5.5/5.6)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/speakers` | list identities (incl. provisional) |
| PATCH | `/speakers/{id}` | rename / confirm |
| POST | `/speakers/merge` | merge two identities (→ job) |
| POST | `/speakers/{id}/split` | split an identity (→ job) |
| POST | `/speakers/enroll` | enroll a known voice from a labeled clip |

### 3.5 Search, jobs, settings, cloud
| Method | Path | Purpose | Traces |
|--------|------|---------|--------|
| GET | `/search?q=` | full-text across transcripts/diary/meetings | FR-7.5 |
| GET | `/jobs` | queued/running/failed steps | FR-7.6 |
| POST | `/jobs/{id}/retry` | retry a failed step | FR-7.6 |
| GET | `/settings` / PATCH `/settings` | read/update config (egress-flagged) | FR-7.7/7.8 |
| GET | `/cloud/remotes` | configured rclone remotes | FR-8.2 |
| POST | `/cloud/sync` | trigger a sync (→ job) | FR-8.3 |
| GET | `/health` | daemon + models + pending-egress status | FR-7.6/7.8 |

## 4. WebSocket (`/api/v1/ws`)

A single channel pushes events so the UI reflects backend state without polling
([04 §3.2](04-system-architecture.md#32-api-server-fastapi-python--backend)):

```jsonc
{ "type": "job.updated",     "data": { "job_id", "type", "status", "attempts", "error?" } }
{ "type": "recording.added", "data": { "recording_id", "device_id" } }
{ "type": "device.connected","data": { "device_id?", "volume", "registered": false } }
{ "type": "diary.updated",   "data": { "date" } }
{ "type": "egress.pending",  "data": { "kind": "cloud_sync|cloud_llm", "detail" } }
```

The `egress.pending` / `egress.started` events back the UI's mandatory egress
indicator ([FR-7.8](03-requirements-specification.md#fr-7-user-interface)).

## 5. Versioning & compatibility

- The path carries the major version (`/api/v1`). Breaking changes bump it.
- The OpenAPI schema is the machine-readable contract; the frontend's typed
  client is generated from it, so drift is caught at build time.

## 6. Open questions

- Token storage/rotation for the opt-in LAN mode.
- Whether to serve the built SPA from the backend (`GET /`) or keep it fully
  separate behind any static host.
- Streaming transcript/audio sync (precise word-level highlight) over WS vs HTTP.
