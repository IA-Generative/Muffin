import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LANGUAGE_PATTERN = re.compile(r"^(auto|[a-z]{2,3}(-[A-Za-z]{2,4})?)$")
SPEECH_FORMATS = ("mp3", "wav", "flac", "opus", "aac")


class VoiceSettingsOut(BaseModel):
    """What the administrator sees of the settings. A key is never in it: only whether there is one."""

    hub_available: bool

    stt_enabled: bool
    # What is called: the address typed, or the hub's when none was.
    stt_base_url: str | None
    stt_uses_hub_address: bool
    stt_has_key: bool
    stt_model: str | None
    stt_language: str
    stt_max_seconds: int
    stt_max_bytes: int
    # Whether people could dictate with these settings: on, with a model, an address and a key.
    stt_ready: bool

    tts_enabled: bool
    tts_base_url: str | None
    tts_uses_hub_address: bool
    tts_has_key: bool
    tts_model: str | None
    tts_voice: str | None
    tts_voice_en: str | None
    tts_format: str
    tts_max_chars: int
    tts_ready: bool


class VoiceSettingsUpdate(BaseModel):
    """The settings changed (the others are left as they are). A base address empty or null: the hub's. `*_api_key`: a
    new key, kept encrypted; `*_clear_key`: forget the one there is."""

    stt_enabled: bool | None = None
    stt_base_url: str | None = Field(default=None, max_length=2048)
    stt_api_key: str | None = Field(default=None, max_length=500)
    stt_clear_key: bool = False
    stt_model: str | None = Field(default=None, max_length=200)
    stt_language: str | None = Field(default=None, max_length=10)
    stt_max_seconds: int | None = Field(default=None, ge=5, le=3600)
    stt_max_bytes: int | None = Field(default=None, ge=100 * 1024)

    tts_enabled: bool | None = None
    tts_base_url: str | None = Field(default=None, max_length=2048)
    tts_api_key: str | None = Field(default=None, max_length=500)
    tts_clear_key: bool = False
    tts_model: str | None = Field(default=None, max_length=200)
    tts_voice: str | None = Field(default=None, max_length=100)
    tts_voice_en: str | None = Field(default=None, max_length=100)
    tts_format: str | None = Field(default=None, max_length=10)
    tts_max_chars: int | None = Field(default=None, ge=100, le=100000)

    @field_validator("stt_language")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        if value is not None and not LANGUAGE_PATTERN.match(value):
            raise ValueError("La langue doit être « auto » ou un code comme fr ou en.")
        return value

    @field_validator("tts_format")
    @classmethod
    def _format(cls, value: str | None) -> str | None:
        if value is not None and value not in SPEECH_FORMATS:
            raise ValueError(f"Le format doit être l'un de : {', '.join(SPEECH_FORMATS)}.")
        return value


class TranscriptionStatus(BaseModel):
    # `server`: the recording is sent to the engine of the administrator; `browser`: the browser dictates, as before.
    mode: Literal["server", "browser"]
    max_seconds: int
    max_bytes: int
    language: str
    # Where the audio goes, for the page to say so: `hub` (the service of models of the organisation), `service`
    # (another address chosen by the administrator), `browser` (the browser's own recognition: nothing leaves it).
    destination: Literal["hub", "service", "browser"]


class SpeechStatus(BaseModel):
    mode: Literal["server", "browser"]
    max_chars: int
    destination: Literal["hub", "service", "browser"]


class VoiceStatusOut(BaseModel):
    transcription: TranscriptionStatus
    speech: SpeechStatus


class TranscriptionOut(BaseModel):
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class SpeechIn(BaseModel):
    text: str = Field(max_length=100000)
    # The language of the text when the page knows it (`fr`, `en`): it picks the voice.
    language: str | None = Field(default=None, max_length=10)


class VoiceTestOut(BaseModel):
    """What a test of an engine says, in words the administrator can act on: no text of the engine is repeated, only a
    code and what was measured."""

    ok: bool
    code: str | None = None
    message: str
    duration_ms: int
    # The text an engine heard (transcription), and the audio an engine made (speech).
    text: str | None = None
    content_type: str | None = None
    audio_bytes: int | None = None
