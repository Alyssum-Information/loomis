"""Real-ffmpeg exercises for the Transcoder wrapper (FR-3.1–3.3).

Skipped wholesale when ffmpeg/ffprobe are not on PATH (offline CI); on a dev
machine they cover the actual shell-out paths the offline suite fakes.
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest

from loomis.core.config import TranscodeSettings
from loomis.pipeline.transcode import TranscodeError, Transcoder

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    """One second of silence as a real PCM WAV."""
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return path


@pytest.fixture
def transcoder() -> Transcoder:
    return Transcoder(TranscodeSettings())


def test_opus_roundtrip_validates(transcoder: Transcoder, wav: Path, tmp_path: Path) -> None:
    opus = tmp_path / "tone.opus"
    transcoder.to_opus(wav, opus)
    assert opus.stat().st_size > 0
    assert transcoder.probe_codec(opus) == "opus"
    assert transcoder.validate(opus, expected_duration=transcoder.probe_duration(wav))


def test_probe_codec_identifies_pcm(transcoder: Transcoder, wav: Path) -> None:
    assert transcoder.probe_codec(wav) == "pcm_s16le"
    assert transcoder.probe_duration(wav) == pytest.approx(1.0, abs=0.1)


def test_to_pcm_wav_produces_playable_wav(
    transcoder: Transcoder, wav: Path, tmp_path: Path
) -> None:
    # opus → PCM is the playback-preview path for codecs browsers can't decode.
    opus = tmp_path / "x.opus"
    transcoder.to_opus(wav, opus)
    pcm = tmp_path / "preview.wav"
    transcoder.to_pcm_wav(opus, pcm)
    assert transcoder.probe_codec(pcm) == "pcm_s16le"
    assert transcoder.validate(pcm, expected_duration=1.0)


def test_validate_rejects_garbage_and_duration_mismatch(
    transcoder: Transcoder, wav: Path, tmp_path: Path
) -> None:
    garbage = tmp_path / "garbage.opus"
    garbage.write_bytes(b"not audio at all")
    assert transcoder.validate(garbage) is False
    assert transcoder.validate(tmp_path / "missing.opus") is False
    # A real file whose duration is far from expectation fails the gate (FR-3.3).
    assert transcoder.validate(wav, expected_duration=100.0) is False


def test_same_src_dst_refused(transcoder: Transcoder, wav: Path) -> None:
    # ffmpeg -y reading and writing one file would corrupt the only copy.
    with pytest.raises(TranscodeError, match="same file"):
        transcoder.to_opus(wav, wav)
    with pytest.raises(TranscodeError, match="same file"):
        transcoder.to_pcm_wav(wav, wav)


def test_failed_encode_raises(transcoder: Transcoder, tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF not really audio")
    with pytest.raises(TranscodeError, match="ffmpeg failed"):
        transcoder.to_opus(bad, tmp_path / "out.opus")
