"""The synthesis engine: the one seam between the service and the model (tests replace `get_engine`)."""

import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from app.config import Settings, load_settings

logger = logging.getLogger("tts.engine")


class Engine(Protocol):
    sample_rate: int
    voices: list[str]

    def synthesize(self, text: str, voice: str, normalize: bool) -> np.ndarray:
        """Mono float waveform in [-1, 1] at `sample_rate`."""
        ...


class KittenEngine:
    """Kitten-TTS 2 on CPU, loaded from local files only (the image carries them, nothing is downloaded)."""

    def __init__(self, settings: Settings) -> None:
        model_dir = Path(settings.model_dir)
        if not (model_dir / "config.json").is_file():
            raise FileNotFoundError(f"no Kitten-TTS 2 model in {model_dir}")

        import torch

        if settings.torch_threads:
            torch.set_num_threads(settings.torch_threads)
        from kittenml import KittenTTS

        self._model = KittenTTS(str(model_dir), device="cpu", weights=settings.weights, decoder=settings.decoder)
        self.sample_rate = int(self._model.sample_rate)
        self.voices = list(self._model.available_voices)
        logger.info(
            "model loaded: weights=%s decoder=%s voices=%d sample_rate=%d",
            settings.weights,
            settings.decoder,
            len(self.voices),
            self.sample_rate,
        )

    def synthesize(self, text: str, voice: str, normalize: bool) -> np.ndarray:
        audio = self._model.generate(text, voice=voice, normalize=normalize)
        return np.asarray(audio, dtype=np.float32).reshape(-1)


_engine: Engine | None = None
_lock = threading.Lock()


def get_engine() -> Engine:
    """The process-wide engine, loaded on first call (blocking: the service calls it from a thread at startup)."""
    global _engine
    with _lock:
        if _engine is None:
            _engine = KittenEngine(load_settings())
        return _engine
