"""Speaker diarization behind a swappable engine interface (FR-5.1, ADR-0007).

"Who spoke when" *within one recording* — output is time turns labelled
``SPEAKER_00``, ``SPEAKER_01``, …. The default ``pyannote`` engine pulls heavy
deps (torch) and is imported lazily, mirroring ``stt.py``. A dep-free ``null``
engine attributes the whole recording to one speaker so offline/CI runs exercise
the full pipeline without a model or GPU.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import DiarizeSettings
from .errors import PermanentJobError

_DIARIZE_HINT = (
    "diarization deps are not installed — run ./install.sh "
    "(or `uv sync --extra stt --extra diarize`)"
)
_FFMPEG_HINT = "ffmpeg not found on PATH — install ffmpeg (whisperx needs it to read audio)"


def _import_whisperx() -> Any:
    try:
        import whisperx  # noqa: PLC0415
    except ImportError as exc:
        raise PermanentJobError(_DIARIZE_HINT) from exc
    if shutil.which("ffmpeg") is None:
        raise PermanentJobError(_FFMPEG_HINT)
    return whisperx


@dataclass(slots=True)
class DiarTurn:
    start: float
    end: float
    label: str


@dataclass(slots=True)
class DiarResult:
    turns: list[DiarTurn] = field(default_factory=list)


class DiarizeEngine(Protocol):
    name: str

    def diarize(
        self, audio: Path, *, min_speakers: int | None, max_speakers: int | None
    ) -> DiarResult: ...


class NullDiarizeEngine:
    """Offline stub: one speaker for the whole recording. No audio decoding, no model."""

    name = "null"

    def diarize(
        self, audio: Path, *, min_speakers: int | None, max_speakers: int | None
    ) -> DiarResult:
        # One turn spanning all time; overlap-mapping assigns every segment to it.
        return DiarResult(turns=[DiarTurn(0.0, math.inf, "SPEAKER_00")])


class PyannoteEngine:
    """pyannote 3.1 via WhisperX; the pipeline loads lazily on first call (ADR-0007)."""

    name = "pyannote"

    def __init__(self, settings: DiarizeSettings) -> None:
        self.model = settings.model
        self._token = settings.hf_token
        self._device = settings.device
        self._pipeline: object | None = None

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import torch  # noqa: PLC0415

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load(self) -> object:
        if self._pipeline is None:
            whisperx = _import_whisperx()
            self._pipeline = whisperx.DiarizationPipeline(
                model_name=self.model, use_auth_token=self._token, device=self._resolve_device()
            )
        return self._pipeline

    def diarize(
        self, audio: Path, *, min_speakers: int | None, max_speakers: int | None
    ) -> DiarResult:
        whisperx = _import_whisperx()
        pipeline = self._load()
        loaded = whisperx.load_audio(str(audio))
        df = pipeline(loaded, min_speakers=min_speakers, max_speakers=max_speakers)  # type: ignore[operator]
        turns = [
            DiarTurn(float(row["start"]), float(row["end"]), str(row["speaker"]))
            for _, row in df.iterrows()
        ]
        return DiarResult(turns=turns)


def get_diarize_engine(settings: DiarizeSettings) -> DiarizeEngine:
    """Construct the diarization engine named by ``[diarize].engine``."""
    if settings.engine == "null":
        return NullDiarizeEngine()
    if settings.engine == "pyannote":
        return PyannoteEngine(settings)
    raise PermanentJobError(f"unknown diarize engine: {settings.engine!r}")
