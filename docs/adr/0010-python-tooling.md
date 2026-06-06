# 0010 — Python tooling: uv + ruff + mypy

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

The project should follow modern open-source Python conventions: reproducible
environments, fast linting/formatting, type safety, and a single configuration
surface. We surveyed the 2026 consensus stack.

## Decision

Adopt the 2026 standard toolchain, all configured in a single **`pyproject.toml`**:

- **[uv](https://github.com/astral-sh/uv)** — Python/version management,
  dependencies, locking (`uv.lock`), and task running. (10–100× faster than pip.)
- **[ruff](https://github.com/astral-sh/ruff)** — linting **and** formatting
  (replaces black + flake8 + isort + pyupgrade + bandit-style rules).
- **mypy** (strict) — static type checking.
- **pytest** — testing.
- **pydantic / pydantic-settings** — data validation and typed configuration.
- **pre-commit** — run ruff + mypy before commits.

Target **Python 3.12+**.

## Alternatives considered

- **pip + venv + requirements.txt** — rejected: slower, no lockfile-by-default,
  more moving parts.
- **Poetry / PDM** — solid, but uv has become the fast default for new
  post-2024 projects and unifies more of the workflow.
- **black + flake8 + isort separately** — rejected: ruff does all three in one
  fast binary.
- **ty / pyright instead of mypy** — reasonable; mypy `--strict` chosen as the
  conservative, widely-supported baseline. Revisitable.

## Consequences

- **Pros:** fast, reproducible, single-config; low-friction contributor setup
  (`uv sync`); consistent style enforced automatically.
- **Cons:** uv is younger than pip (acceptable; widely adopted by 2026);
  strict typing adds upfront annotation effort (pays off in a pipeline-heavy
  codebase).
- All tool config (ruff, mypy, pytest, coverage, build) lives in
  `pyproject.toml` — no `setup.py`/`setup.cfg`/`.flake8`.

## References

- "Python Project Setup 2026: uv + Ruff" — KDnuggets
- "Modern Python Tooling 2026: uv, Ruff, mypy" — softaims
