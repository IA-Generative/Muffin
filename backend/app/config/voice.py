from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSettings(BaseSettings):
    """The voice in the chat (#517): dictating a message by recording it, and hearing an answer read aloud. What an
    administrator turns on - the engine, its address, model and voice - is a setting of the application
    (Administration -> Voix); these are the limits that no setting may lift."""

    # How many transcriptions, and how many readings, one person may start per minute - all attempts counted: an engine
    # that fails has still been called.
    VOICE_TRANSCRIPTIONS_PER_USER_PER_MINUTE: int = 6
    VOICE_SPEECH_PER_USER_PER_MINUTE: int = 20
    # The most an administrator may allow for a recording: its weight (bytes; the limit of the OpenAI API) and its
    # length (seconds). The weight is the hard bound; the length is the one the recorder of the page stops at, and
    # the one the person reports - the server does not decode audio.
    VOICE_STT_MAX_BYTES_LIMIT: int = 25 * 1024 * 1024
    VOICE_STT_MAX_SECONDS_LIMIT: int = 600
    # The longest text an administrator may allow to be read in one request, and the heaviest audio taken back.
    VOICE_TTS_MAX_CHARS_LIMIT: int = 8000
    VOICE_TTS_MAX_AUDIO_BYTES: int = 25 * 1024 * 1024
    # The longest text a transcription may give back (characters): what goes in the composer.
    VOICE_STT_MAX_TEXT_CHARS: int = 20000
    # How long the engine has to answer (seconds).
    VOICE_REQUEST_TIMEOUT_SECONDS: float = 120.0

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
