"""Loomis backend — local-first voice lifelogger.

See ../../docs for the design. This package hosts the core, pipeline, daemon,
and FastAPI API. Pre-alpha: config + DB, the health API, and the M1 backup core
(device registration + the SHA-256 safety-spine import) are implemented; the
processing pipeline lands in later milestones.
"""

__version__ = "0.0.0"
