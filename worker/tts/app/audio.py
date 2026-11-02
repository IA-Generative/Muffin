"""Waveform encoding: the formats of the OpenAI speech route."""

import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class AudioFormat:
    media_type: str
    sf_format: str | None  # None: raw PCM, written by hand


FORMATS: dict[str, AudioFormat] = {
    "wav": AudioFormat("audio/wav", "WAV"),
    "flac": AudioFormat("audio/flac", "FLAC"),
    "mp3": AudioFormat("audio/mpeg", "MP3"),
    "pcm": AudioFormat("audio/pcm", None),
}


def change_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    """Pitch-preserving time stretch (phase vocoder): artefacts grow with the factor. The model has no speed control."""
    if speed == 1.0:
        return audio
    import librosa

    return librosa.effects.time_stretch(audio, rate=speed)


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")


def encode(audio: np.ndarray, sample_rate: int, response_format: str) -> bytes:
    """`audio` as the bytes of `response_format` (mono, 16 bits; `pcm` is raw little-endian samples)."""
    spec = FORMATS[response_format]
    samples = to_int16(audio)
    if spec.sf_format is None:
        return samples.tobytes()
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format=spec.sf_format, subtype=None if spec.sf_format == "MP3" else "PCM_16")
    return buffer.getvalue()
