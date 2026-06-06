# 0006 — Database: SQLite

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Loomis needs durable storage for metadata, transcripts index, the backup ledger,
the job queue, speaker identities, and summaries. It is a **single-user,
local-first** desktop application. We want zero server setup, durability across
crashes, concurrent read (UI) alongside write (daemon), and easy backup.

## Decision

Use **SQLite** as the metadata database (the user's stated local-first default),
in **WAL mode** for concurrent readers, with **versioned migrations**
([FR-9.3](../03-requirements-specification.md#fr-9-configuration--data-management)). Bulk content
(audio, full transcripts, Markdown) lives on the filesystem, referenced by path
([05 Data Model](../05-data-model-and-storage.md)).

The same SQLite file also backs the **durable job queue**
([04 §7](../04-system-architecture.md#7-concurrency--durability-model)) and can
host vector search via the `sqlite-vec` extension if/when needed
([ADR-0007](0007-speaker-diarization-pyannote.md)).

## Alternatives considered

- **PostgreSQL** — rejected: requires a running server; overkill for single-user
  local; against the zero-setup goal.
- **DuckDB** — great for analytics, but SQLite is the better fit for
  transactional app state + a job queue; revisit only for heavy analytics.
- **Plain JSON/flat files for everything** — rejected: no transactions, poor
  concurrency, painful queries for timeline/search.

## Consequences

- **Pros:** zero-setup, single-file, transactional, durable, trivially
  backed-up/synced; FTS5 gives full-text search; WAL enables UI-reads during
  daemon-writes.
- **Cons:** single-writer model (fine here — only the daemon writes); very large
  vector sets eventually want `sqlite-vec` or an external index (deferred).
- Keeping heavy bytes on disk keeps the DB small and fast.

## References

- SQLite WAL — https://www.sqlite.org/wal.html
- FTS5 — https://www.sqlite.org/fts5.html
- sqlite-vec — https://github.com/asg017/sqlite-vec
