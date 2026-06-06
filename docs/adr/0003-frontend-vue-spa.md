# 0003 — Frontend: Vue + Vuetify SPA over a FastAPI backend

- **Status:** Accepted
- **Date:** 2026-06-07

## Context

The project uses a conventional **backend / frontend split**: Python backend
code in `backend/`, frontend code in `web/`. The UI's job is to browse a lifelog
timeline, play audio with speaker-labeled transcripts, search, manage speakers,
and watch job health — while a background daemon does the real work (backup, STT,
summarization) independently. We want a first-class web frontend and a clean HTTP
contract between the two halves.

## Decision

- **Frontend:** a **Vue 3 + Vuetify** single-page app in `web/`, built with
  **Vite**, state via **Pinia**. Vuetify provides a complete Material component
  set (data tables, timeline, navigation) well-suited to a data-dense lifelog.
- **Backend API:** the Python backend (`backend/`) exposes a **FastAPI**
  **REST + WebSocket** surface ([11 API Specification](../11-api-specification.md)).
  REST for queries/commands; WebSocket for live job/health/egress push.
- The SPA talks to the backend **only** over HTTP/WebSocket; it never touches
  SQLite or the file library. Default bind `127.0.0.1`; LAN exposure opt-in.
- The daemon and the API run in one Python process by default (shared DB +
  library) and can be split unchanged.

FastAPI is chosen for the backend because pydantic is already in the stack
(shared models, validation), it is async, has native WebSocket support, and
emits an **OpenAPI** schema that can generate the frontend's typed API client.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Pure-Python web UI** (NiceGUI / Reflex) | Doesn't fit a separate `web/` JavaScript frontend with its own toolchain. |
| **Native desktop** (PySide6/Qt) | Heavier, Windows-centric packaging; lifelog timeline/list UX is cheaper in the browser, and the worker should run headless regardless. |
| **React / Svelte** instead of Vue | All viable; Vue + Vuetify chosen per project preference for a batteries-included Material UI with low ceremony. |
| **Flask / Litestar / Django REST** for the API | FastAPI wins on pydantic reuse, async, built-in WebSocket + OpenAPI; least friction here. |
| **No separate API** (server-rendered) | Defeats the explicit frontend/backend split. |

## Consequences

- **Pros:** clean separation of concerns; rich, modern UI; typed API client from
  OpenAPI; frontend and backend evolve and deploy independently; browse from any
  browser (incl. phone on LAN).
- **Cons:** two toolchains to set up (uv for `backend/`, npm/pnpm + Vite for
  `web/`); a build step for the SPA; an HTTP API to design, version, and secure
  — see [11 API Specification](../11-api-specification.md).
- **Privacy unchanged:** API binds to localhost by default; LAN exposure
  (`[api].host = 0.0.0.0`) and any cloud egress remain opt-in and surfaced in the
  UI ([09 Security & Privacy](../09-security-and-privacy-model.md)).
- **Device events** are still handled by the daemon's watcher
  ([ADR-0011](0011-usb-device-detection.md)), not the browser.

## References

- Vue 3 — https://vuejs.org · Vuetify — https://vuetifyjs.com · Vite — https://vite.dev
- Pinia — https://pinia.vuejs.org
- FastAPI — https://fastapi.tiangolo.com
