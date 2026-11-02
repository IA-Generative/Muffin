"""Settings, read once from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

WEIGHTS_VARIANTS = ("packed", "emb4", "full")


@dataclass(frozen=True)
class Settings:
    api_key: str | None = None
    max_chars: int = 4000
    max_concurrency: int = 1
    request_timeout_seconds: float = 120.0
    default_voice: str = "French"
    weights: str = "packed"
    decoder: str = "default"
    model_dir: str = "/models/kitten-tts-2"
    model_name: str = "kitten-tts-2"
    torch_threads: int | None = None
    retry_after_seconds: int = 5


def _positive(env: Mapping[str, str], name: str, default: float, cast: type) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {raw!r}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    defaults = Settings()
    weights = env.get("TTS_WEIGHTS", "").strip() or defaults.weights
    if weights not in WEIGHTS_VARIANTS:
        raise ValueError(f"TTS_WEIGHTS must be one of {', '.join(WEIGHTS_VARIANTS)}, got {weights!r}")
    threads = env.get("TTS_TORCH_THREADS", "").strip()
    return Settings(
        api_key=env.get("TTS_API_KEY", "").strip() or None,
        max_chars=int(_positive(env, "TTS_MAX_CHARS", defaults.max_chars, int)),
        max_concurrency=int(_positive(env, "TTS_MAX_CONCURRENCY", defaults.max_concurrency, int)),
        request_timeout_seconds=float(
            _positive(env, "TTS_REQUEST_TIMEOUT_SECONDS", defaults.request_timeout_seconds, float)
        ),
        default_voice=env.get("TTS_DEFAULT_VOICE", "").strip() or defaults.default_voice,
        weights=weights,
        decoder=env.get("TTS_DECODER", "").strip() or defaults.decoder,
        model_dir=env.get("TTS_MODEL_DIR", "").strip() or defaults.model_dir,
        model_name=env.get("TTS_MODEL_NAME", "").strip() or defaults.model_name,
        torch_threads=int(_positive(env, "TTS_TORCH_THREADS", 1, int)) if threads else None,
        retry_after_seconds=int(_positive(env, "TTS_RETRY_AFTER_SECONDS", defaults.retry_after_seconds, int)),
    )
