"""Speech-to-text behind a swappable engine interface (FR-4.4, ADR-0002).

The default ``whisperx`` engine gives multilingual Whisper accuracy plus forced
word alignment, but pulls heavy deps (torch); it is imported lazily so the base
install and the test suite stay light. A dep-free ``null`` engine produces a
deterministic empty transcript for offline/dev runs and CI.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import SttSettings
from .errors import PermanentJobError

_STT_HINT = "whisperx is not installed — run ./install.sh (or `uv sync --extra stt --extra gpu`)"
_FFMPEG_HINT = "ffmpeg not found on PATH — install ffmpeg (whisperx needs it to read audio)"


def _import_whisperx() -> Any:
    try:
        import whisperx  # noqa: PLC0415
    except ImportError as exc:
        raise PermanentJobError(_STT_HINT) from exc
    if shutil.which("ffmpeg") is None:
        raise PermanentJobError(_FFMPEG_HINT)
    return whisperx


@dataclass(slots=True)
class STTWord:
    start: float
    end: float
    word: str


@dataclass(slots=True)
class STTSegment:
    start: float
    end: float
    text: str
    words: list[STTWord] = field(default_factory=list)


@dataclass(slots=True)
class STTResult:
    language: str
    text: str
    segments: list[STTSegment] = field(default_factory=list)

    def to_json(self, *, engine: str, model: str | None) -> dict[str, object]:
        """Serialisable form persisted to ``transcripts/<recording_id>.json``."""
        return {
            "engine": engine,
            "model": model,
            "language": self.language,
            "text": self.text,
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "words": [{"start": w.start, "end": w.end, "word": w.word} for w in s.words],
                }
                for s in self.segments
            ],
        }


class STTEngine(Protocol):
    name: str
    model: str | None

    def transcribe(self, audio: Path, *, language: str | None) -> STTResult: ...


class NullSTTEngine:
    """Offline stub: valid, empty transcript. No audio decoding, no model, no network."""

    name = "null"
    model: str | None = None

    def transcribe(self, audio: Path, *, language: str | None) -> STTResult:
        return STTResult(language=language or "und", text="", segments=[])


class WhisperXEngine:
    """WhisperX adapter; the model loads lazily on first ``transcribe`` (04 §7)."""

    name = "whisperx"

    def __init__(self, settings: SttSettings) -> None:
        self.model: str | None = settings.model
        self._device = settings.device
        self._compute_type = settings.compute_type
        self._model: object | None = None

    def _resolve_device(self) -> tuple[str, str]:
        device = self._device
        compute = self._compute_type
        if device == "auto" or compute == "auto":
            try:
                import torch  # noqa: PLC0415

                has_cuda = bool(torch.cuda.is_available())
            except Exception:
                has_cuda = False
            if device == "auto":
                device = "cuda" if has_cuda else "cpu"
            if compute == "auto":
                compute = "float16" if device == "cuda" else "int8"
        return device, compute

    def _load(self) -> object:
        if self._model is None:
            whisperx = _import_whisperx()
            device, compute = self._resolve_device()
            self._model = whisperx.load_model(self.model, device, compute_type=compute)
        return self._model

    def transcribe(self, audio: Path, *, language: str | None) -> STTResult:
        whisperx = _import_whisperx()
        model = self._load()
        device, _ = self._resolve_device()
        loaded = whisperx.load_audio(str(audio))
        lang = None if (language in (None, "", "auto")) else language
        raw = model.transcribe(loaded, language=lang)  # type: ignore[attr-defined]
        detected = str(raw.get("language", lang or "und"))

        # Forced alignment for accurate word timestamps (the WhisperX value-add).
        segments: list[STTSegment] = []
        try:
            align_model, meta = whisperx.load_align_model(language_code=detected, device=device)
            aligned = whisperx.align(raw["segments"], align_model, meta, loaded, device)
            raw_segments = aligned["segments"]
        except Exception:
            raw_segments = raw["segments"]  # alignment is best-effort; fall back to coarse spans

        for seg in raw_segments:
            words = [
                STTWord(
                    float(w.get("start", seg["start"])),
                    float(w.get("end", seg["end"])),
                    str(w.get("word", "")).strip(),
                )
                for w in seg.get("words", [])
            ]
            segments.append(
                STTSegment(float(seg["start"]), float(seg["end"]), str(seg["text"]).strip(), words)
            )

        text = " ".join(s.text for s in segments).strip()
        return STTResult(language=detected, text=text, segments=segments)


def get_engine(settings: SttSettings) -> STTEngine:
    """Construct the STT engine named by ``[stt].engine``."""
    if settings.engine == "null":
        return NullSTTEngine()
    if settings.engine == "whisperx":
        return WhisperXEngine(settings)
    raise PermanentJobError(f"unknown stt engine: {settings.engine!r}")
