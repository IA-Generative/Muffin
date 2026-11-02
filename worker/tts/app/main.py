"""OpenAI-compatible text-to-speech service (Kitten-TTS 2).

The text to speak is never logged: only its length, the voice, the format and the durations.
"""

import asyncio
import hmac
import logging
import threading
import time
import traceback
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from app import engine as engine_module
from app.audio import FORMATS, change_speed, encode
from app.config import Settings, load_settings
from app.voices import is_english_voice, resolve_voice

logger = logging.getLogger("tts")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    logger.addHandler(handler)

MIN_SPEED = 0.5
MAX_SPEED = 2.0


class ApiError(Exception):
    def __init__(self, status: int, message: str, error_type: str, code: str, headers: dict[str, str] | None = None):
        self.status = status
        self.message = message
        self.error_type = error_type
        self.code = code
        self.headers = headers or {}


def error_response(error: ApiError) -> JSONResponse:
    body = {"error": {"message": error.message, "type": error.error_type, "code": error.code}}
    return JSONResponse(body, status_code=error.status, headers=error.headers)


class SpeechRequest(BaseModel):
    # Other fields of the OpenAI schema (`instructions`, `stream_format`...) are accepted and ignored.
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    input: str
    voice: str | None = None
    response_format: str | None = None
    speed: float | None = None


class Slots:
    """Bounded concurrency: a slot is taken without waiting, or not at all (no queue)."""

    def __init__(self, count: int) -> None:
        self._free = count
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._free == 0:
                return False
            self._free -= 1
            return True

    def release(self) -> None:
        with self._lock:
            self._free += 1


def _where(exc: BaseException) -> str:
    """Where an exception was raised, without its message (which could quote the text)."""
    frames = traceback.extract_tb(exc.__traceback__)
    last = frames[-1] if frames else None
    return f"{type(exc).__name__} at {last.filename}:{last.lineno}" if last else type(exc).__name__


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    executor = ThreadPoolExecutor(max_workers=settings.max_concurrency, thread_name_prefix="tts")
    slots = Slots(settings.max_concurrency)

    def load_model(app: FastAPI) -> None:
        try:
            engine = engine_module.get_engine()
            if resolve_voice(None, engine.voices, settings.default_voice) is None:
                raise ValueError(
                    f"default voice {settings.default_voice!r} is not one of the {len(engine.voices)} voices"
                )
        except Exception as exc:
            logger.error("model loading failed: %s", _where(exc))
            app.state.load_error = _where(exc)
            return
        app.state.engine = engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = None
        app.state.load_error = None
        # A daemon thread: the server answers /health (503) while the model loads, and a stop never waits for it.
        threading.Thread(target=load_model, args=(app,), daemon=True, name="tts-loader").start()
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Muffin TTS (Kitten-TTS 2)", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, error: ApiError) -> JSONResponse:
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, error: RequestValidationError) -> JSONResponse:
        fields = ", ".join(
            sorted({".".join(str(p) for p in e["loc"] if p != "body") or "body" for e in error.errors()})
        )
        return error_response(ApiError(422, f"Invalid request: {fields}", "invalid_request_error", "invalid_request"))

    def require_auth(request: Request) -> None:
        if settings.api_key is None:
            return
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        supplied = token.strip().encode() if scheme.lower() == "bearer" else b""
        if not hmac.compare_digest(supplied, settings.api_key.encode()):
            raise ApiError(
                401,
                "Missing or invalid API key.",
                "invalid_request_error",
                "invalid_api_key",
                {"WWW-Authenticate": "Bearer"},
            )

    def loaded_engine(request: Request) -> engine_module.Engine:
        engine = request.app.state.engine
        if engine is None:
            raise ApiError(
                503,
                "The model is not ready.",
                "server_error",
                "model_not_ready",
                {"Retry-After": str(settings.retry_after_seconds)},
            )
        return engine

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        if request.app.state.engine is not None:
            return JSONResponse({"status": "ok"})
        status = "failed" if request.app.state.load_error else "loading"
        return JSONResponse({"status": status}, status_code=503)

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    async def list_models() -> dict[str, Any]:
        model = {"id": settings.model_name, "object": "model", "created": 0, "owned_by": "KittenML"}
        return {"object": "list", "data": [model]}

    @app.get("/v1/audio/voices", dependencies=[Depends(require_auth)])
    async def list_voices(request: Request) -> dict[str, Any]:
        engine = loaded_engine(request)
        return {"default": settings.default_voice, "voices": sorted(engine.voices)}

    @app.post("/v1/audio/speech", dependencies=[Depends(require_auth)])
    async def speech(body: SpeechRequest, request: Request) -> Response:
        invalid = "invalid_request_error"
        if not body.input.strip():
            raise ApiError(422, "`input` must not be empty.", invalid, "input_empty")
        if len(body.input) > settings.max_chars:
            raise ApiError(413, f"`input` is limited to {settings.max_chars} characters.", invalid, "input_too_long")
        response_format = (body.response_format or "wav").lower()
        if response_format not in FORMATS:
            raise ApiError(
                422, f"`response_format` must be one of: {', '.join(FORMATS)}.", invalid, "unsupported_response_format"
            )
        speed = 1.0 if body.speed is None else body.speed
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ApiError(422, f"`speed` must be between {MIN_SPEED} and {MAX_SPEED}.", invalid, "invalid_speed")

        engine = loaded_engine(request)
        voice = resolve_voice(body.voice, engine.voices, settings.default_voice)
        if voice is None:
            raise ApiError(
                422,
                f"Unknown voice: {len(engine.voices)} voices are available, see GET /v1/audio/voices.",
                invalid,
                "unknown_voice",
            )

        if not slots.try_acquire():
            raise ApiError(
                429,
                "The service is busy: retry shortly.",
                "rate_limit_error",
                "busy",
                {"Retry-After": str(settings.retry_after_seconds)},
            )

        def synthesize() -> tuple[bytes, float]:
            audio = engine.synthesize(body.input, voice, normalize=is_english_voice(voice))
            audio = change_speed(audio, speed)
            return encode(audio, engine.sample_rate, response_format), len(audio) / engine.sample_rate

        started = time.monotonic()
        try:
            future = executor.submit(synthesize)
        except BaseException:
            slots.release()
            raise
        # The slot is freed when the work really ends, not when the request gives up: a timed-out synthesis keeps
        # running (a model call cannot be interrupted) and must keep counting against the concurrency.
        future.add_done_callback(lambda _: slots.release())
        try:
            payload, seconds = await asyncio.wait_for(asyncio.wrap_future(future), settings.request_timeout_seconds)
        except TimeoutError:
            logger.warning("timeout: chars=%d voice=%s after %.1fs", len(body.input), voice, time.monotonic() - started)
            raise ApiError(
                504,
                "The synthesis took too long.",
                "server_error",
                "timeout",
                {"Retry-After": str(settings.retry_after_seconds)},
            ) from None
        except Exception as exc:
            logger.error("synthesis failed: chars=%d voice=%s error=%s", len(body.input), voice, _where(exc))
            raise ApiError(500, "The synthesis failed.", "server_error", "synthesis_failed") from None

        elapsed = time.monotonic() - started
        logger.info(
            "speech: chars=%d voice=%s format=%s speed=%.2f audio=%.2fs took=%.2fs",
            len(body.input),
            voice,
            response_format,
            speed,
            seconds,
            elapsed,
        )
        return Response(payload, media_type=FORMATS[response_format].media_type)

    return app


app = create_app()
