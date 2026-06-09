"""Voiceprint embedding + cross-recording identity matching (FR-5.2–5.4).

Per diarized speaker we compute one L2-normalized embedding, then cosine-compare
it against known identities' centroids to **assign**, **create a new provisional
identity**, or flag as **uncertain** (feature 04 §4–5). Matching is in-memory
brute force (fine for thousands of identities; ``sqlite-vec`` is the documented
upgrade path, §8).

Kept numpy-free in the base install: embeddings are plain float tuples, stored as
``float32`` BLOBs. The heavy ``pyannote`` embedder is imported lazily, mirroring
``stt.py`` / ``diarize.py``; the ``null`` embedder derives a deterministic vector
from the diarization label so offline/CI runs match consistently.
"""

from __future__ import annotations

import hashlib
import math
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import SpeakerIdSettings
from .diarize import DiarTurn

Vector = tuple[float, ...]

_NULL_DIM = 32


# --- serialization + vector math (stdlib only) ---


def vec_to_blob(vec: Vector) -> bytes:
    return array("f", vec).tobytes()


def blob_to_vec(blob: bytes) -> Vector:
    a = array("f")
    a.frombytes(blob)
    return tuple(a)


def l2_normalize(vec: Vector) -> Vector:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return tuple(v / norm for v in vec)


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity. Inputs need not be normalized; guards zero vectors."""
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def centroid(vecs: list[Vector]) -> Vector:
    """Mean of a speaker's voiceprints, L2-normalized (the comparison key, §5)."""
    if not vecs:
        return ()
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            acc[i] += v[i]
    n = float(len(vecs))
    return l2_normalize(tuple(x / n for x in acc))


# --- embedding engines ---


class SpeakerEmbedder(Protocol):
    name: str

    def embed(self, audio: Path, turns: list[DiarTurn]) -> dict[str, Vector]:
        """Return one L2-normalized embedding per distinct diarization label."""
        ...


class NullEmbedder:
    """Offline stub: deterministic per-label vector (same label → same identity)."""

    name = "null"

    def embed(self, audio: Path, turns: list[DiarTurn]) -> dict[str, Vector]:
        out: dict[str, Vector] = {}
        for label in {t.label for t in turns}:
            digest = hashlib.sha256(label.encode("utf-8")).digest()
            vec = tuple(b / 255.0 for b in digest[:_NULL_DIM])
            out[label] = l2_normalize(vec)
        return out


class PyannoteEmbedder:
    """pyannote embedding model; loads lazily on first ``embed`` (FR-5.2)."""

    name = "pyannote"

    def __init__(self, settings: SpeakerIdSettings) -> None:
        self.model = settings.model
        self._device = settings.device
        self._inference: object | None = None

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import torch  # type: ignore[import-not-found]  # noqa: PLC0415

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load(self) -> object:
        if self._inference is None:
            import torch  # noqa: PLC0415
            from pyannote.audio import (  # type: ignore[import-not-found]  # noqa: PLC0415
                Inference,
                Model,
            )

            model = Model.from_pretrained(self.model)
            self._inference = Inference(
                model, window="whole", device=torch.device(self._resolve_device())
            )
        return self._inference

    def embed(self, audio: Path, turns: list[DiarTurn]) -> dict[str, Vector]:
        from pyannote.core import Segment  # type: ignore[import-not-found]  # noqa: PLC0415

        inference = self._load()
        # Aggregate per label: average the embeddings of that speaker's turns.
        per_label: dict[str, list[Vector]] = {}
        for turn in turns:
            if not math.isfinite(turn.end) or turn.end <= turn.start:
                continue
            crop = Segment(turn.start, turn.end)
            raw = inference.crop(str(audio), crop)  # type: ignore[attr-defined]
            vec = tuple(float(x) for x in raw)
            per_label.setdefault(turn.label, []).append(l2_normalize(vec))
        return {label: centroid(vecs) for label, vecs in per_label.items() if vecs}


def get_embedder(settings: SpeakerIdSettings) -> SpeakerEmbedder:
    """Construct the embedder named by ``[speaker_id].engine``."""
    if settings.engine == "null":
        return NullEmbedder()
    if settings.engine == "pyannote":
        return PyannoteEmbedder(settings)
    raise ValueError(f"unknown speaker_id engine: {settings.engine!r}")


# --- matching (FR-5.3, FR-5.4) ---


@dataclass(slots=True)
class MatchDecision:
    action: str  # "assign" | "new" | "uncertain"
    speaker_id: int | None  # set for assign/uncertain; None for new
    needs_review: bool


def match(
    emb: Vector,
    known: list[tuple[int, Vector]],
    cfg: SpeakerIdSettings,
) -> MatchDecision:
    """Decide an unknown embedding against known centroids (feature 04 §5).

    - ``best ≥ match_threshold`` **and** ``best − second ≥ margin`` → assign.
    - ``best < new_identity_below`` → new provisional identity.
    - otherwise → assign provisionally but flag for review.
    """
    if not known:
        return MatchDecision(action="new", speaker_id=None, needs_review=False)

    scored = sorted(((cosine(emb, c), sid) for sid, c in known), reverse=True)
    best_sim, best_sid = scored[0]
    second_sim = scored[1][0] if len(scored) > 1 else -1.0

    if best_sim >= cfg.match_threshold and (best_sim - second_sim) >= cfg.margin:
        return MatchDecision(action="assign", speaker_id=best_sid, needs_review=False)
    if best_sim < cfg.new_identity_below:
        return MatchDecision(action="new", speaker_id=None, needs_review=False)
    return MatchDecision(action="uncertain", speaker_id=best_sid, needs_review=True)
