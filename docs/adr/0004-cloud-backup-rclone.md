# 0004 — Cloud backup backend: rclone

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Feature #7 wants optional backup to **OneDrive and other common cloud storage**.
Cloud is strictly opt-in (local-first default). We want one integration that
covers many providers, is robust for backup (resumable, checksum-verified), and
doesn't bloat our Python dependency tree per provider.

Options surveyed (June 2026):

- **rclone** — a mature CLI managing **70+ cloud providers** (OneDrive, Google
  Drive, Dropbox, S3, …). Preserves timestamps, verifies checksums, resumes
  interrupted transfers, supports scheduled one-way sync. One integration → all
  providers.
- **msgraph-sdk (Python)** — official, async, pure-Python — but **OneDrive
  only**; every other provider would be a separate SDK and code path.

## Decision

Use **rclone** as the cloud backup backend, wrapped behind a `CloudSync`
interface ([FR-8](../03-requirements-specification.md#fr-8-cloud-sync-optional)). Loomis shells
out to rclone for configured remotes; default direction is **push-only** and
sync **never deletes local source data**.

## Alternatives considered

- **msgraph-sdk** — rejected as the primary backend (single-provider). Could be
  added later as a no-external-binary native OneDrive option behind the same
  interface if avoiding the rclone dependency matters to some users.
- **Per-provider Python SDKs** — rejected; N integrations to build and maintain.
- **Native OS sync clients** (OneDrive app, etc.) — rejected; out of Loomis's
  control, no programmatic verification/scheduling.

## Consequences

- **Pros:** one integration → many clouds; battle-tested integrity (checksums,
  resume); scheduling; minimal Python deps.
- **Cons:** requires the **rclone binary** present (install/ship + path config);
  remotes are configured via rclone's own tooling (we surface status, not full
  credential management); shelling out needs careful error handling.
- Credentials live in rclone's config, **not** in Loomis's repo or logs
  ([NFR-9](../03-requirements-specification.md#2-non-functional-requirements)).

## References

- rclone — https://rclone.org · OneDrive backend — https://rclone.org/onedrive/
- msgraph-sdk-python — https://github.com/microsoftgraph/msgraph-sdk-python
