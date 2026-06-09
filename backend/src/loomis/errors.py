"""Shared error types for the pipeline."""

from __future__ import annotations


class PermanentJobError(Exception):
    """A job failure that retrying cannot fix — a missing optional dependency or a
    bad configuration value.

    The job runner parks these immediately instead of burning retry attempts, and
    surfaces the message verbatim on the recording / in the Jobs view so the fix
    (e.g. running ``./install.sh``) is obvious.
    """
