import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEFAULT_STT_MAX_SECONDS = 300
DEFAULT_STT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TTS_MAX_CHARS = 4000


class VoiceEngineSettings(Base):
    """The voice in the chat (#517): one row (id is always 1), admin-only. Both functions are **off by default**: the
    chat then dictates with the browser and reads with the browser's own voice, as it always did.

    The address of an engine and its key are the hub's when left empty. A key an administrator types is kept encrypted
    (`StoredSecret`, one purpose for each function) and never read back: the settings say only that there is one."""

    __tablename__ = "voice_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Transcription: the person records a message, it is turned into text. An OpenAI-compatible
    # `POST {base}/audio/transcriptions`.
    stt_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # An OpenAI-compatible address ending in /v1; None: the hub's.
    stt_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    stt_secret_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stt_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # `auto`, or a language code that is given to the engine as a hint.
    stt_language: Mapped[str] = mapped_column(String(10), nullable=False, default="auto", server_default="auto")
    stt_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_STT_MAX_SECONDS, server_default=str(DEFAULT_STT_MAX_SECONDS)
    )
    stt_max_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_STT_MAX_BYTES, server_default=str(DEFAULT_STT_MAX_BYTES)
    )

    # Speech: an answer is read aloud. An OpenAI-compatible `POST {base}/audio/speech`.
    tts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tts_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    tts_secret_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tts_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The voice for the answers (a name the engine knows), and the one for an answer in English when it is another.
    tts_voice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tts_voice_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tts_format: Mapped[str] = mapped_column(String(10), nullable=False, default="mp3", server_default="mp3")
    tts_max_chars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_TTS_MAX_CHARS, server_default=str(DEFAULT_TTS_MAX_CHARS)
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
