"""The voice in the chat (#517): dictating by recording a message that an engine turns into text, and hearing an answer
read aloud. Both are optional, **off by default**, and go through an OpenAI-compatible service chosen by the
administrator - the hub's own when no address is given, or another (a service of the organisation, a pod such as
`worker/tts`). With none, the chat dictates and reads with the browser, as it always did.

What is kept to, whatever the engine is:
- **Nothing is called before it is allowed.** The function must be on and complete, the input in bounds, the rate
  respected: otherwise the answer is a clear code and the engine has not been called.
- **The bytes are checked, not the sender's word.** A recording is one of the containers a browser records, and the
  type announced is the type found. Nothing is decoded here: that is the engine's work.
- **Nothing is kept.** The audio goes to the engine and is dropped, and the text is returned and dropped: neither is
  written in the database, in the object store, or in the logs - only the size, the length, the engine's latency and a
  code. The key of the engine is never given back, nor logged.
- **Nothing of the engine's reaches the person but a code**: not its text, not the key."""

import io
import re
import time
import wave
from dataclasses import dataclass

from loguru import logger
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings, VoiceSettings
from app.connectors import async_redis
from app.core import audio_bytes, url_guard
from app.core.audio_bytes import NotAudioError
from app.core.secret_store import SecretStoreError
from app.core.security.factory import RequestContext
from app.models.token_usage import TokenUsageKind
from app.models.voice import VoiceEngineSettings
from app.repositories.voice_repository import VoiceSettingsRepository
from app.schemas.internal_pipeline import LlmUsageContext
from app.schemas.voice import (
    SpeechStatus,
    TranscriptionOut,
    TranscriptionStatus,
    VoiceSettingsOut,
    VoiceSettingsUpdate,
    VoiceStatusOut,
    VoiceTestOut,
)
from app.services.app_settings_service import NotAdminError
from app.services.secret_store_service import SecretNotFoundError, SecretStore
from app.services.usage_service import UsageService

# Module attributes so that tests change them with monkeypatch.setattr.
_settings = VoiceSettings()
_llm_settings = LlmSettings()

_PURPOSES = {"stt": "voice-transcription-key", "tts": "voice-speech-key"}
_SPEECH_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "opus": "audio/ogg",
    "aac": "audio/aac",
}
_TEST_SPEECH = "Bonjour, ceci est un essai de la lecture à voix haute."
_DEFAULT_VOICE = "alloy"
_TOLERANCE_SECONDS = 2.0


class VoiceError(Exception):
    """A voice request that did not happen, said with a code that does not change and words for the person. `status` is
    the HTTP status the API answers with."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Transcribed:
    text: str
    language: str | None
    seconds: float | None


def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    """The client of an engine. One per call: the address and the key can change between two."""
    return AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=_settings.VOICE_REQUEST_TIMEOUT_SECONDS, max_retries=0
    )


def silent_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """A short recording of silence, made here: what a test of an engine sends - no sample is shipped."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


class VoiceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = VoiceSettingsRepository(db)

    # --- the administrator's settings ---

    @staticmethod
    def _require_admin(user: RequestContext) -> None:
        if not user.is_admin:
            raise NotAdminError(user.user_id)

    @staticmethod
    def _hub_available() -> bool:
        return _llm_settings.is_configured

    def _ready(self, row: VoiceEngineSettings, prefix: str) -> bool:
        base_url = getattr(row, f"{prefix}_base_url")
        has_key = getattr(row, f"{prefix}_secret_id") is not None or (
            not base_url and bool(_llm_settings.OPENAI_API_KEY)
        )
        return bool(
            getattr(row, f"{prefix}_enabled")
            and getattr(row, f"{prefix}_model")
            and has_key
            and (base_url or self._hub_available())
        )

    def _present(self, row: VoiceEngineSettings) -> VoiceSettingsOut:
        hub = _llm_settings.OPENAI_API_BASE_URL or None
        return VoiceSettingsOut(
            hub_available=self._hub_available(),
            stt_enabled=row.stt_enabled,
            stt_base_url=row.stt_base_url or hub,
            stt_uses_hub_address=not row.stt_base_url,
            stt_has_key=row.stt_secret_id is not None,
            stt_model=row.stt_model,
            stt_language=row.stt_language,
            stt_max_seconds=row.stt_max_seconds,
            stt_max_bytes=row.stt_max_bytes,
            stt_ready=self._ready(row, "stt"),
            tts_enabled=row.tts_enabled,
            tts_base_url=row.tts_base_url or hub,
            tts_uses_hub_address=not row.tts_base_url,
            tts_has_key=row.tts_secret_id is not None,
            tts_model=row.tts_model,
            tts_voice=row.tts_voice,
            tts_voice_en=row.tts_voice_en,
            tts_format=row.tts_format,
            tts_max_chars=row.tts_max_chars,
            tts_ready=self._ready(row, "tts"),
        )

    async def get_settings(self, user: RequestContext) -> VoiceSettingsOut:
        self._require_admin(user)
        return self._present(await self.settings.get_or_create())

    async def update_settings(self, user: RequestContext, body: VoiceSettingsUpdate) -> VoiceSettingsOut:
        self._require_admin(user)
        row = await self.settings.get_or_create()
        changes = body.model_dump(
            exclude_unset=True, exclude={"stt_api_key", "stt_clear_key", "tts_api_key", "tts_clear_key"}
        )
        for field in ("stt_base_url", "tts_base_url"):
            if field in changes:
                changes[field] = await self._checked_address(changes[field])
        for field in ("stt_model", "tts_model", "tts_voice", "tts_voice_en"):
            if field in changes:
                changes[field] = (changes[field] or "").strip() or None
        if "stt_max_bytes" in changes and changes["stt_max_bytes"] > _settings.VOICE_STT_MAX_BYTES_LIMIT:
            raise VoiceError("reglage_invalide", "Cette taille maximale dépasse la limite de l'installation.", 422)
        if "stt_max_seconds" in changes and changes["stt_max_seconds"] > _settings.VOICE_STT_MAX_SECONDS_LIMIT:
            raise VoiceError("reglage_invalide", "Cette durée maximale dépasse la limite de l'installation.", 422)
        if "tts_max_chars" in changes and changes["tts_max_chars"] > _settings.VOICE_TTS_MAX_CHARS_LIMIT:
            raise VoiceError("reglage_invalide", "Ce nombre de caractères dépasse la limite de l'installation.", 422)
        nullable = {"stt_base_url", "tts_base_url", "stt_model", "tts_model", "tts_voice", "tts_voice_en"}
        for key, value in changes.items():
            if value is not None or key in nullable:
                setattr(row, key, value)
        for prefix, new_key, clear in (
            ("stt", body.stt_api_key, body.stt_clear_key),
            ("tts", body.tts_api_key, body.tts_clear_key),
        ):
            if clear and getattr(row, f"{prefix}_secret_id") is not None:
                await self._forget_key(row, prefix)
            elif new_key:
                await self._set_key(row, prefix, user, new_key.strip())
            self._check_consistent(row, prefix)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(f"Voice settings changed by {user.user_id}: {', '.join(sorted(changes))}")
        return self._present(row)

    @staticmethod
    async def _checked_address(value: str | None) -> str | None:
        """The address of an engine: http(s), no credentials in it. It may be on the internal network - a pod or a
        gateway is often there - since it is typed by an administrator."""
        if not value or not value.strip():
            return None
        try:
            return url_guard.check_form(value, restrict_domains=False).rstrip("/")
        except url_guard.UrlRefusedError as error:
            raise VoiceError("reglage_invalide", str(error), 422) from error

    def _check_consistent(self, row: VoiceEngineSettings, prefix: str) -> None:
        base_url = getattr(row, f"{prefix}_base_url")
        if base_url and base_url.rstrip("/") != _llm_settings.OPENAI_API_BASE_URL.rstrip("/"):
            if getattr(row, f"{prefix}_secret_id") is None:
                # The hub's key is never sent to another address.
                raise VoiceError("reglage_invalide", "Une autre adresse que celle du hub demande sa propre clé.", 422)
        if getattr(row, f"{prefix}_enabled") and not (getattr(row, f"{prefix}_model") or "").strip():
            raise VoiceError("reglage_invalide", "Choisissez un modèle avant d'activer la fonction.", 422)

    async def _set_key(self, row: VoiceEngineSettings, prefix: str, user: RequestContext, key: str) -> None:
        store, purpose = SecretStore(self.db), _PURPOSES[prefix]
        secret_id = getattr(row, f"{prefix}_secret_id")
        if secret_id is None:
            created = await store.put(owner=None, purpose=purpose, plaintext=key, created_by=user.user_id)
            setattr(row, f"{prefix}_secret_id", created.id)
        else:
            await store.replace(secret_id, key, owner=None, purpose=purpose)

    async def _forget_key(self, row: VoiceEngineSettings, prefix: str) -> None:
        secret_id = getattr(row, f"{prefix}_secret_id")
        if secret_id is not None:
            try:
                await SecretStore(self.db).delete(secret_id, owner=None, purpose=_PURPOSES[prefix])
            except SecretNotFoundError:
                pass
            setattr(row, f"{prefix}_secret_id", None)

    async def _engine(self, row: VoiceEngineSettings, prefix: str) -> tuple[str, str, str]:
        """(address, key, model) to call: the administrator's or the hub's - the hub's key to the hub's address only."""
        base_url = getattr(row, f"{prefix}_base_url") or _llm_settings.OPENAI_API_BASE_URL
        secret_id = getattr(row, f"{prefix}_secret_id")
        if secret_id is not None:
            try:
                key = await SecretStore(self.db).reveal(secret_id, owner=None, purpose=_PURPOSES[prefix])
            except (SecretNotFoundError, SecretStoreError):
                logger.warning("The key of a voice engine could not be read")
                key = ""
        else:
            key = _llm_settings.OPENAI_API_KEY if not getattr(row, f"{prefix}_base_url") else ""
        model = getattr(row, f"{prefix}_model")
        if not base_url or not key or not model:
            raise VoiceError("non_configuree", "Cette fonction vocale n'est pas configurée complètement.", 409)
        return base_url, key, model

    # --- what the page is told ---

    def _destination(self, row: VoiceEngineSettings, prefix: str) -> str:
        return "service" if getattr(row, f"{prefix}_base_url") else "hub"

    async def status(self, user: RequestContext) -> VoiceStatusOut:
        """Whether the page records and reads through the server, or leaves it to the browser. Nothing is called and no
        key is read to tell."""
        row = await self.settings.get() or VoiceEngineSettings(id=1)
        stt = self._ready(row, "stt")
        tts = self._ready(row, "tts")
        return VoiceStatusOut(
            transcription=TranscriptionStatus(
                mode="server" if stt else "browser",
                max_seconds=row.stt_max_seconds or 300,
                max_bytes=min(
                    row.stt_max_bytes or _settings.VOICE_STT_MAX_BYTES_LIMIT, _settings.VOICE_STT_MAX_BYTES_LIMIT
                ),
                language=row.stt_language or "auto",
                destination=self._destination(row, "stt") if stt else "browser",
            ),
            speech=SpeechStatus(
                mode="server" if tts else "browser",
                max_chars=row.tts_max_chars or 4000,
                destination=self._destination(row, "tts") if tts else "browser",
            ),
        )

    # --- the rate ---

    @staticmethod
    async def _take_rate(user_id: str, what: str, per_minute: int) -> None:
        """One unit of the minute's rate, taken **before** the engine is called. A rate that cannot be checked stops the
        call: the engine costs, unlike the answer of a page."""
        try:
            redis = async_redis()
            key = f"voice:{what}:{user_id}:{int(time.time() // 60)}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 90)
            if count > per_minute:
                raise VoiceError("trop_de_demandes", "Trop de demandes à la suite : patientez un instant.", 429)
        except VoiceError:
            raise
        except Exception as error:
            logger.warning("The voice rate could not be checked", exc_info=True)
            raise VoiceError(
                "limite_indisponible", "La limite de demandes ne peut pas être vérifiée pour le moment.", 503
            ) from error

    # --- transcription ---

    @staticmethod
    def _language_hint(requested: str | None, configured: str) -> str | None:
        """The language given to the engine as a hint, two letters: the person's own when they gave one, else the
        administrator's, else none (the engine finds it)."""
        for candidate in (requested, configured):
            value = (candidate or "").strip().lower()
            if value and value != "auto":
                return value.split("-")[0]
        return None

    def _check_recording(
        self, row: VoiceEngineSettings, data: bytes, announced: str | None, seconds: float | None
    ) -> tuple[audio_bytes.AudioInfo, float | None]:
        if not data:
            raise VoiceError("audio_vide", "L'enregistrement est vide.", 422)
        limit = min(row.stt_max_bytes, _settings.VOICE_STT_MAX_BYTES_LIMIT)
        if len(data) > limit:
            raise VoiceError(
                "fichier_trop_lourd",
                f"L'enregistrement dépasse {limit // (1024 * 1024)} Mo : faites-le plus court.",
                413,
            )
        try:
            info = audio_bytes.sniff(data)
        except NotAudioError as error:
            raise VoiceError(
                "type_refuse", "Ce fichier n'est pas un enregistrement audio pris en charge.", 415
            ) from error
        if (announced or "").split(";")[0].strip().lower() not in ("", "application/octet-stream"):
            family = audio_bytes.family_of(announced)
            if family is None or family != info.kind:
                raise VoiceError("type_incoherent", "Le type annoncé ne correspond pas au contenu du fichier.", 415)
        # The length: certain for a WAV, which says it in its header; for the others it is what the page reports.
        length = audio_bytes.wav_seconds(data) or seconds
        if length is not None and length > row.stt_max_seconds + _TOLERANCE_SECONDS:
            raise VoiceError(
                "audio_trop_long",
                f"L'enregistrement dépasse {row.stt_max_seconds // 60 or 1} minute(s) : faites-le plus court.",
                413,
            )
        return info, length

    async def transcribe(
        self,
        user: RequestContext,
        data: bytes,
        announced_type: str | None,
        language: str | None = None,
        seconds: float | None = None,
    ) -> TranscriptionOut:
        row = await self.settings.get()
        if row is None or not self._ready(row, "stt"):
            raise VoiceError("fonction_desactivee", "La transcription par le serveur n'est pas activée.", 404)
        if language is not None and not re.fullmatch(r"auto|[A-Za-z]{2,3}(-[A-Za-z]{2,4})?", language.strip()):
            raise VoiceError("langue_invalide", "La langue demandée n'est pas valide.", 422)
        info, length = self._check_recording(row, data, announced_type, seconds)
        await self._take_rate(user.user_id, "stt", _settings.VOICE_TRANSCRIPTIONS_PER_USER_PER_MINUTE)
        base_url, key, model = await self._engine(row, "stt")
        result = await self._ask_transcription(
            base_url, key, model, data, info, self._language_hint(language, row.stt_language)
        )
        await self._record(user.user_id, "transcription", model, seconds=length or result.seconds or 0.0)
        return TranscriptionOut(text=result.text, language=result.language, duration_seconds=length or result.seconds)

    async def _ask_transcription(
        self, base_url: str, key: str, model: str, data: bytes, info: audio_bytes.AudioInfo, language: str | None
    ) -> Transcribed:
        arguments: dict = {"model": model, "file": (f"audio.{info.extension}", data, info.content_type)}
        if language:
            arguments["language"] = language
        client = _client(base_url, key)
        started = time.monotonic()
        try:
            response = await client.audio.transcriptions.create(response_format="json", **arguments)
        except Exception as error:
            raise self._engine_error(error, "transcription") from error
        finally:
            await client.close()
        text = re.sub(r"\s+", " ", str(getattr(response, "text", "") or "")).strip()
        logger.info(
            f"Transcription: {len(data)} bytes, {len(text)} characters, {int((time.monotonic() - started) * 1000)} ms"
        )
        if len(text) > _settings.VOICE_STT_MAX_TEXT_CHARS:
            text = text[: _settings.VOICE_STT_MAX_TEXT_CHARS]
        duration = getattr(response, "duration", None)
        return Transcribed(
            text=text,
            language=getattr(response, "language", None) or language,
            seconds=float(duration) if isinstance(duration, int | float) else None,
        )

    # --- speech ---

    async def speak(self, user: RequestContext, text: str, language: str | None = None) -> tuple[bytes, str]:
        """The audio of a text read aloud, and its type."""
        row = await self.settings.get()
        if row is None or not self._ready(row, "tts"):
            raise VoiceError("fonction_desactivee", "La lecture par le serveur n'est pas activée.", 404)
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            raise VoiceError("texte_vide", "Il n'y a rien à lire.", 422)
        limit = min(row.tts_max_chars, _settings.VOICE_TTS_MAX_CHARS_LIMIT)
        if len(text) > limit:
            raise VoiceError("texte_trop_long", f"Ce texte dépasse {limit} caractères : lisez-en une partie.", 413)
        await self._take_rate(user.user_id, "tts", _settings.VOICE_SPEECH_PER_USER_PER_MINUTE)
        base_url, key, model = await self._engine(row, "tts")
        voice = (
            row.tts_voice_en if (language or "").lower().startswith("en") and row.tts_voice_en else row.tts_voice
        ) or _DEFAULT_VOICE
        audio, content_type = await self._ask_speech(base_url, key, model, voice, text, row.tts_format)
        await self._record(user.user_id, "speech", model, characters=len(text))
        return audio, content_type

    async def _ask_speech(
        self, base_url: str, key: str, model: str, voice: str, text: str, audio_format: str
    ) -> tuple[bytes, str]:
        client = _client(base_url, key)
        started = time.monotonic()
        try:
            response = await client.audio.speech.create(
                model=model, voice=voice, input=text, response_format=audio_format
            )
            data = response.content
        except Exception as error:
            raise self._engine_error(error, "speech") from error
        finally:
            await client.close()
        if not data or len(data) > _settings.VOICE_TTS_MAX_AUDIO_BYTES:
            raise VoiceError("audio_invalide", "Le service n'a pas renvoyé un audio utilisable.", 502)
        try:
            audio_bytes.sniff(data)
        except NotAudioError as error:
            raise VoiceError("audio_invalide", "Le service n'a pas renvoyé un audio utilisable.", 502) from error
        logger.info(f"Speech: {len(text)} characters, {len(data)} bytes, {int((time.monotonic() - started) * 1000)} ms")
        return data, _SPEECH_TYPES.get(audio_format, "application/octet-stream")

    # --- the engines' failures ---

    @staticmethod
    def _engine_error(error: Exception, what: str) -> VoiceError:
        """What an engine's failure is called here. Nothing of its text goes on: it may repeat part of the key or of
        what was sent. The log has the status and the code."""
        status = getattr(error, "status_code", None)
        code = getattr(error, "code", None)
        logger.warning(f"The {what} engine failed: {type(error).__name__} status={status} code={code}")
        if isinstance(error, AuthenticationError | PermissionDeniedError):
            return VoiceError("cle_refusee", f"Le service refuse la clé ou l'accès (HTTP {status}).", 502)
        if isinstance(error, NotFoundError):
            return VoiceError(
                "modele_introuvable",
                "Ce service ne fournit pas cette fonction ou ne connaît pas ce modèle (HTTP 404).",
                502,
            )
        if isinstance(error, BadRequestError):
            if status == 415 or code in ("unsupported_media_type", "invalid_audio", "unsupported_format"):
                return VoiceError("format_refuse", "Le service refuse le format de l'audio.", 502)
            return VoiceError("parametre_refuse", "Le service refuse un paramètre de la demande (HTTP 400).", 502)
        if isinstance(error, RateLimitError):
            return VoiceError("moteur_surcharge", "Le service est saturé : réessayez plus tard.", 503)
        if isinstance(error, APITimeoutError):
            return VoiceError("delai_depasse", "Le service a mis trop de temps à répondre.", 504)
        if isinstance(error, APIConnectionError):
            return VoiceError("moteur_indisponible", "Le service vocal est injoignable.", 503)
        if isinstance(error, APIStatusError):
            if status == 415:
                return VoiceError("format_refuse", "Le service refuse le format de l'audio.", 502)
            return VoiceError(
                "moteur_en_erreur", f"Le service a échoué (HTTP {status}).", 502 if (status or 500) < 500 else 503
            )
        return VoiceError("moteur_en_erreur", "Le service vocal a échoué.", 502)

    # --- the tests of an engine ---

    async def test_transcription(self, user: RequestContext) -> VoiceTestOut:
        """Sends a second of silence made here: validates the address, the key, the model and the route, and says what
        was measured. Nothing of the engine's text is repeated."""
        self._require_admin(user)
        return await self._test(await self.settings.get_or_create(), "stt", user)

    async def test_speech(self, user: RequestContext) -> VoiceTestOut:
        self._require_admin(user)
        return await self._test(await self.settings.get_or_create(), "tts", user)

    async def _test(self, row: VoiceEngineSettings, prefix: str, user: RequestContext) -> VoiceTestOut:
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            base_url, key, model = await self._engine(row, prefix)
            if prefix == "stt":
                result = await self._ask_transcription(
                    base_url,
                    key,
                    model,
                    silent_wav(),
                    audio_bytes.sniff(silent_wav()),
                    self._language_hint(None, row.stt_language),
                )
                return VoiceTestOut(
                    ok=True,
                    message="Le service a répondu : la transcription fonctionne.",
                    duration_ms=elapsed(),
                    text=result.text,
                )
            voice = row.tts_voice or _DEFAULT_VOICE
            audio, content_type = await self._ask_speech(base_url, key, model, voice, _TEST_SPEECH, row.tts_format)
            return VoiceTestOut(
                ok=True,
                message="Le service a produit un audio : la lecture fonctionne.",
                duration_ms=elapsed(),
                content_type=content_type,
                audio_bytes=len(audio),
            )
        except VoiceError as error:
            logger.info(f"Voice test by {user.user_id} failed: {error.code}")
            return VoiceTestOut(ok=False, code=error.code, message=error.message, duration_ms=elapsed())

    # --- the consumption ---

    async def _record(self, user_id: str, step: str, model: str, *, seconds: float = 0.0, characters: int = 0) -> None:
        """What a transcription or a reading costs is seconds of audio and characters, not tokens: a row of usage."""
        await UsageService(self.db).record(
            LlmUsageContext(step=step, user_id=user_id),
            TokenUsageKind.AUDIO,
            model,
            0,
            0,
            audio_seconds=seconds,
            characters=characters,
        )
