# 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Loomis makes several non-obvious technology choices (STT engine, UI model, LLM
strategy, cloud backend). Without a record of *why*, future contributors will
either blindly follow or needlessly re-debate them, and the reasoning behind
trade-offs will be lost.

## Decision

Use **Architecture Decision Records**. Each significant, hard-to-reverse choice
gets a numbered Markdown file in `docs/adr/` using the Nygard template
(Context / Decision / Alternatives / Consequences). ADRs are immutable once
accepted; superseding a decision means writing a new ADR that references the old.

## Alternatives considered

- **No formal record** (rely on commit messages / tribal knowledge) — rejected;
  doesn't survive contributor turnover.
- **A single "decisions" page** — rejected; grows unwieldy and loses the
  immutable, point-in-time character that makes ADRs trustworthy.

## Consequences

- Small overhead per decision; large payoff in onboarding and avoiding churn.
- The ADR index in [README.md](README.md) is the canonical map of "why things
  are the way they are."
