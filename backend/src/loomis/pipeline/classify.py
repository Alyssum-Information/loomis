"""Diary-vs-meeting classification heuristics (FR-6.1, feature 05 §2).

Cheap signals first — distinct speaker count and owner-dominance by speaking time;
the LLM only confirms when the heuristic is unsure (handled in the pipeline). Bias
ties toward *diary*: a stray meeting filed in the diary is cheaper than fragmenting
the lifelog.
"""

from __future__ import annotations

from typing import Literal

from ..core.config import SummariesSettings
from ..core.models import ClassifyResult, Segment


def _speaker_key(seg: Segment) -> str | None:
    if seg.speaker_id is not None:
        return f"s{seg.speaker_id}"
    return seg.diarization_label


def classify_segments(segments: list[Segment], cfg: SummariesSettings) -> ClassifyResult:
    """Heuristic label + confidence from a recording's segments (no LLM)."""
    durations: dict[str, float] = {}
    for seg in segments:
        key = _speaker_key(seg)
        if key is None:
            continue
        durations[key] = durations.get(key, 0.0) + max(0.0, seg.end_s - seg.start_s)

    distinct = len(durations)
    if distinct == 0:
        # Nothing to go on — fall back to the configured tie-break bias (defaults to diary).
        bias: Literal["diary", "meeting"] = (
            "meeting" if cfg.ambiguous_bias == "meeting" else "diary"
        )
        return ClassifyResult(type=bias, confidence=0.0, reason="no speaker segments")

    if distinct == 1:
        return ClassifyResult(type="diary", confidence=0.9, reason="single speaker")

    total = sum(durations.values()) or 1.0
    dominant = max(durations.values()) / total
    if dominant >= cfg.solo_dominance:
        return ClassifyResult(
            type="diary", confidence=0.6, reason=f"owner-dominant ({dominant:.2f})"
        )
    return ClassifyResult(type="meeting", confidence=0.7, reason=f"{distinct} speakers")
