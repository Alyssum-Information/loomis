"""Shared foundation: config, database, domain models, repository, storage, events.

Everything here is dependency-light and importable from any layer; ``core``
itself never imports from ``ingest``, ``pipeline``, or ``api``
(see docs/04-system-architecture.md §12).
"""
