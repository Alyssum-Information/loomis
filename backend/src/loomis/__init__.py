"""Loomis backend — local-first voice lifelogger.

See ../../docs for the design. This package hosts the core, pipeline, daemon,
and FastAPI API. Pre-alpha: M1 (safe ingest — backup + transcription) and M2
(local intelligence — diarization, speaker identity, diary/meeting summaries)
are implemented; the REST/WebSocket API + web UI land in M3.
"""

__version__ = "0.2.0"
