"""The processing pipeline: durable job runner + every per-recording step.

``runner`` claims and executes jobs from the SQLite queue; ``steps`` maps each
job type to its handler (transcode → stt → diarize → speaker_id → classify →
diary/meeting). The remaining modules are the step implementations behind
swappable engine interfaces (docs/04-system-architecture.md §6–7).
"""
