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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..core.config import SpeakerIdSettings
from ..core.errors import PermanentJobError
from ..core.vectors import Vector, centroid, cosine, l2_normalize
from .diarize import DiarTurn

_NULL_DIM = 32
_SAMPLE_RATE = 16000  # whisperx.load_audio decodes to mono float32 at this rate
_EMBED_HINT = (
    "speaker embedding deps are not installed — run ./install.sh (or `uv sync --extra diarize`)"
)


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
            import torch  # noqa: PLC0415

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load(self) -> object:
        if self._inference is None:
            try:
                import torch  # noqa: PLC0415
                from pyannote.audio import (  # noqa: PLC0415
                    Inference,
                    Model,
                )
            except ImportError as exc:
                raise PermanentJobError(_EMBED_HINT) from exc

            model = Model.from_pretrained(self.model)
            if model is None:
                raise PermanentJobError(f"could not load embedding model {self.model!r}")
            self._inference = Inference(
                model, window="whole", device=torch.device(self._resolve_device())
            )
        return self._inference

    def _load_in_memory(self, audio: Path) -> dict[str, object]:
        """Decode the file to an in-memory waveform for pyannote.

        pyannote's file-path crop decodes via torchcodec, whose Windows DLLs are often
        broken; passing a ``{"waveform", "sample_rate"}`` dict makes it skip that path
        entirely. We reuse whisperx's ffmpeg-CLI decoder (mono float32 @ 16 kHz) — the
        same one STT and diarization already rely on.
        """
        import torch  # noqa: PLC0415

        try:
            import whisperx  # noqa: PLC0415
        except ImportError as exc:
            raise PermanentJobError(_EMBED_HINT) from exc
        wav = whisperx.load_audio(str(audio))  # np.float32, mono, 16 kHz
        waveform = torch.from_numpy(wav).unsqueeze(0)  # (channel=1, time)
        return {"waveform": waveform, "sample_rate": _SAMPLE_RATE}

    def embed(self, audio: Path, turns: list[DiarTurn]) -> dict[str, Vector]:
        from pyannote.core import Segment  # noqa: PLC0415

        inference = self._load()
        file = self._load_in_memory(audio)
        # Aggregate per label: average the embeddings of that speaker's turns.
        per_label: dict[str, list[Vector]] = {}
        for turn in turns:
            if not math.isfinite(turn.end) or turn.end <= turn.start:
                continue
            crop = Segment(turn.start, turn.end)
            raw = inference.crop(file, crop)  # type: ignore[attr-defined]
            vec = tuple(float(x) for x in raw)
            per_label.setdefault(turn.label, []).append(l2_normalize(vec))
        return {label: centroid(vecs) for label, vecs in per_label.items() if vecs}


def get_embedder(settings: SpeakerIdSettings) -> SpeakerEmbedder:
    """Construct the embedder named by ``[speaker_id].engine``."""
    if settings.engine == "null":
        return NullEmbedder()
    if settings.engine == "pyannote":
        return PyannoteEmbedder(settings)
    raise PermanentJobError(f"unknown speaker_id engine: {settings.engine!r}")


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
