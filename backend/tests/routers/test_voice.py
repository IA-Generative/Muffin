"""The voice in the chat (#517): off until an administrator turns it on, nothing called before it is allowed, the bytes
checked and not the sender's word, nothing kept, a key that is never read back, and the browser as the way out."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from loguru import logger
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)
from sqlalchemy import delete, func, select

from app.connectors import async_redis
from app.core import secret_store, storage
from app.core.secret_store import LocalProvider
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.stored_secret import StoredSecret
from app.models.token_usage import TokenUsage, TokenUsageKind
from app.models.voice import VoiceEngineSettings
from app.repositories.token_usage_repository import TokenUsageRepository
from app.routers.voice import router as voice_router
from app.services import voice_service
from app.services.voice_service import silent_wav
from tests.routers.test_images import ALICE, BOB, HUB_KEY, HUB_URL, OWN_KEY, ROOT, become, status_error

WEBM = b"\x1a\x45\xdf\xa3" + bytes(300)
MP3 = b"ID3\x04\x00" + bytes(300)
LEAK = "PROVIDER-TEXT-THAT-MUST-NOT-LEAK"


class Engine:
    """The service that listens and speaks: what it was asked, and what it answers."""

    def __init__(self) -> None:
        self.transcriptions: list[dict] = []
        self.speeches: list[dict] = []
        self.error: Exception | None = None
        self.text = "  Bonjour   tout le monde \n"
        self.language: str | None = None
        self.duration: float | None = None
        self.audio: bytes = MP3

    def client(self, base_url: str, api_key: str):
        engine = self

        class Transcriptions:
            async def create(self, **kwargs):
                engine.transcriptions.append({"base_url": base_url, "api_key": api_key, **kwargs})
                if engine.error:
                    raise engine.error
                return SimpleNamespace(text=engine.text, language=engine.language, duration=engine.duration)

        class Speech:
            async def create(self, **kwargs):
                engine.speeches.append({"base_url": base_url, "api_key": api_key, **kwargs})
                if engine.error:
                    raise engine.error
                return SimpleNamespace(content=engine.audio)

        class Audio:
            transcriptions = Transcriptions()
            speech = Speech()

        class Client:
            audio = Audio()

            async def close(self) -> None:
                return None

        return Client()


@pytest.fixture
def engine(monkeypatch) -> Engine:
    fake = Engine()
    monkeypatch.setattr(voice_service, "_client", fake.client)
    return fake


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    yield lines
    logger.remove(sink)


async def _forget_counters() -> None:
    redis = async_redis()
    for key in await redis.keys("voice:*"):
        await redis.delete(key)


@pytest.fixture
async def client(monkeypatch, engine):
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k1", bytes([1]) * 32)]))
    monkeypatch.setattr(voice_service._llm_settings, "OPENAI_API_BASE_URL", HUB_URL)
    monkeypatch.setattr(voice_service._llm_settings, "OPENAI_API_KEY", HUB_KEY)
    monkeypatch.setattr(voice_service._settings, "VOICE_TRANSCRIPTIONS_PER_USER_PER_MINUTE", 1000)
    monkeypatch.setattr(voice_service._settings, "VOICE_SPEECH_PER_USER_PER_MINUTE", 1000)
    await _forget_counters()
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    await _forget_counters()
    async with async_session_factory() as session:
        await session.execute(delete(VoiceEngineSettings))
        await session.execute(delete(StoredSecret))
        await session.execute(delete(TokenUsage).where(TokenUsage.kind == TokenUsageKind.AUDIO))
        await session.commit()


async def configure(client, **fields) -> dict:
    """Turns both functions on as an administrator, with the hub's address and key unless told otherwise."""
    become(ROOT, admin=True)
    body = {
        "stt_enabled": True,
        "stt_model": "whisper-1",
        "tts_enabled": True,
        "tts_model": "tts-1",
        "tts_voice": "French",
        **fields,
    }
    response = await client.patch("/api/admin/voice", json=body)
    assert response.status_code == 200, response.text
    become(ALICE)
    return response.json()


async def dictate(client, data: bytes = WEBM, content_type: str = "audio/webm;codecs=opus", **form):
    return await client.post("/api/transcriptions", files={"file": ("voice", data, content_type)}, data=form)


async def read_aloud(client, text: str = "Bonjour à tous.", **fields):
    return await client.post("/api/speech", json={"text": text, **fields})


async def usage_rows() -> list[TokenUsage]:
    async with async_session_factory() as session:
        result = await session.execute(select(TokenUsage).where(TokenUsage.kind == TokenUsageKind.AUDIO))
        return list(result.scalars())


# --- off by default ---


async def test_nothing_is_offered_nor_called_until_an_administrator_turns_it_on(client, engine):
    status = (await client.get("/api/voice/status")).json()
    heard = await dictate(client)
    read = await read_aloud(client)

    assert status["transcription"]["mode"] == "browser" and status["transcription"]["destination"] == "browser"
    assert status["speech"]["mode"] == "browser" and status["speech"]["destination"] == "browser"
    assert heard.status_code == 404 and heard.json()["detail"]["code"] == "fonction_desactivee"
    assert read.status_code == 404 and read.json()["detail"]["code"] == "fonction_desactivee"
    assert engine.transcriptions == [] and engine.speeches == []


async def test_a_function_without_a_model_cannot_be_turned_on(client):
    become(ROOT, admin=True)

    refused = await client.patch("/api/admin/voice", json={"stt_enabled": True})

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "reglage_invalide"
    become(ALICE)
    assert (await client.get("/api/voice/status")).json()["transcription"]["mode"] == "browser"


async def test_each_function_is_offered_on_its_own_and_says_where_the_audio_goes(client):
    await configure(client, tts_enabled=False)
    first = (await client.get("/api/voice/status")).json()

    become(ROOT, admin=True)
    await client.patch(
        "/api/admin/voice",
        json={"tts_enabled": True, "tts_base_url": "http://worker-tts:8080/v1", "tts_api_key": OWN_KEY},
    )
    become(ALICE)
    second = (await client.get("/api/voice/status")).json()

    assert first["transcription"]["mode"] == "server" and first["transcription"]["destination"] == "hub"
    assert first["speech"]["mode"] == "browser"
    assert second["speech"]["mode"] == "server" and second["speech"]["destination"] == "service"
    assert second["transcription"]["max_seconds"] == 300 and second["speech"]["max_chars"] == 4000


# --- the settings ---


async def test_only_an_administrator_reads_or_changes_the_settings_and_runs_the_tests(client):
    assert (await client.get("/api/admin/voice")).status_code == 403
    assert (await client.patch("/api/admin/voice", json={"stt_model": "x"})).status_code == 403
    assert (await client.post("/api/admin/voice/test-transcription")).status_code == 403
    assert (await client.post("/api/admin/voice/test-speech")).status_code == 403


async def test_a_key_is_kept_encrypted_never_read_back_and_never_logged(client, engine, logs):
    settings = await configure(
        client,
        stt_base_url="https://stt.example.test/v1",
        stt_api_key=OWN_KEY,
        tts_base_url="https://tts.example.test/v1",
        tts_api_key=OWN_KEY,
    )
    await dictate(client)
    await read_aloud(client)

    assert settings["stt_has_key"] is True and settings["tts_has_key"] is True and OWN_KEY not in str(settings)
    become(ROOT, admin=True)
    assert OWN_KEY not in (await client.get("/api/admin/voice")).text
    async with async_session_factory() as session:
        stored = (await session.execute(select(StoredSecret))).scalars().all()
    assert len(stored) == 2 and all(OWN_KEY not in str(row.ciphertext) for row in stored)
    assert engine.transcriptions[0]["api_key"] == OWN_KEY and engine.speeches[0]["api_key"] == OWN_KEY
    assert OWN_KEY not in "".join(logs) and HUB_KEY not in "".join(logs)


async def test_the_hub_is_called_with_its_own_key_when_no_address_is_given(client, engine):
    await configure(client)

    await dictate(client)
    await read_aloud(client)

    assert engine.transcriptions[0]["base_url"] == HUB_URL and engine.transcriptions[0]["api_key"] == HUB_KEY
    assert engine.speeches[0]["base_url"] == HUB_URL and engine.speeches[0]["api_key"] == HUB_KEY


async def test_another_address_needs_its_own_key_and_never_gets_the_hubs(client, engine):
    become(ROOT, admin=True)
    refused = await client.patch(
        "/api/admin/voice", json={"stt_model": "m", "stt_enabled": True, "stt_base_url": "https://stt.example.test/v1"}
    )
    become(ALICE)

    assert refused.status_code == 422 and "propre clé" in refused.json()["detail"]["message"]
    assert engine.transcriptions == []


@pytest.mark.parametrize(
    "address", ["ftp://stt.example.test/v1", "https://user:pass@stt.example.test/v1", "not an address"]
)
async def test_an_address_that_is_not_http_or_carries_credentials_is_refused(client, address):
    become(ROOT, admin=True)

    refused = await client.patch("/api/admin/voice", json={"stt_base_url": address, "stt_api_key": OWN_KEY})

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "reglage_invalide"


async def test_an_address_on_the_internal_network_is_allowed_to_an_administrator(client):
    become(ROOT, admin=True)

    response = await client.patch(
        "/api/admin/voice", json={"tts_base_url": "http://worker-tts:8080/v1", "tts_api_key": OWN_KEY}
    )

    assert response.status_code == 200 and response.json()["tts_base_url"] == "http://worker-tts:8080/v1"


async def test_the_limits_of_the_installation_cannot_be_lifted_by_a_setting(client):
    become(ROOT, admin=True)

    for body in (
        {"stt_max_bytes": 10 * 1024 * 1024 * 1024},
        {"stt_max_seconds": 3000},
        {"tts_max_chars": 90000},
    ):
        assert (await client.patch("/api/admin/voice", json=body)).status_code == 422, body


async def test_forgetting_a_key_forgets_it(client):
    await configure(client, stt_base_url="https://stt.example.test/v1", stt_api_key=OWN_KEY)
    become(ROOT, admin=True)

    response = await client.patch("/api/admin/voice", json={"stt_base_url": "", "stt_clear_key": True})

    assert response.json()["stt_has_key"] is False and response.json()["stt_uses_hub_address"] is True
    async with async_session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(StoredSecret))).scalar_one() == 0


# --- transcription ---


async def test_a_recording_becomes_text_in_one_call_with_the_model_and_the_language_hint(client, engine):
    await configure(client, stt_language="fr")
    engine.language = "fr"

    response = await dictate(client, duration_seconds="12.4")

    assert response.status_code == 200
    assert response.json() == {"text": "Bonjour tout le monde", "language": "fr", "duration_seconds": 12.4}
    [call] = engine.transcriptions
    assert call["model"] == "whisper-1" and call["language"] == "fr" and call["response_format"] == "json"
    name, data, content_type = call["file"]
    assert name == "audio.webm" and data == WEBM and content_type == "audio/webm"


async def test_the_language_of_the_person_wins_then_the_administrators_then_the_engine_finds_it(client, engine):
    await configure(client, stt_language="fr")
    await dictate(client, language="en-GB")
    await configure(client, stt_language="auto")
    await dictate(client, language="auto")
    await dictate(client)
    await configure(client, stt_language="de")
    await dictate(client)

    assert [call.get("language") for call in engine.transcriptions] == ["en", None, None, "de"]


async def test_a_language_that_is_not_one_is_refused_before_the_engine_is_called(client, engine):
    await configure(client)

    refused = await dictate(client, language="fr; drop table")

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "langue_invalide"
    assert engine.transcriptions == []


@pytest.mark.parametrize(
    "data, announced",
    [
        (b"%PDF-1.7\n" + bytes(300), "audio/webm"),
        (b"<html>not found</html>", "audio/wav"),
        (bytes(300), "audio/mpeg"),
    ],
)
async def test_what_is_not_audio_is_refused_whatever_it_is_called_and_the_engine_is_not_called(
    client, engine, data, announced
):
    await configure(client)

    refused = await dictate(client, data, announced)

    assert refused.status_code == 415 and refused.json()["detail"]["code"] == "type_refuse"
    assert engine.transcriptions == []


@pytest.mark.parametrize("announced", ["audio/wav", "audio/mpeg", "application/pdf", "text/plain", "image/png"])
async def test_a_type_that_does_not_match_the_content_is_refused(client, engine, announced):
    await configure(client)

    refused = await dictate(client, WEBM, announced)

    assert refused.status_code == 415 and refused.json()["detail"]["code"] == "type_incoherent"
    assert engine.transcriptions == []


async def test_a_generic_type_is_accepted_when_the_bytes_are_audio(client, engine):
    await configure(client)

    assert (await dictate(client, MP3, "application/octet-stream")).status_code == 200
    assert engine.transcriptions[0]["file"][0] == "audio.mp3"


async def test_an_empty_recording_is_refused(client, engine):
    await configure(client)

    refused = await dictate(client, b"")

    assert (
        refused.status_code == 422 and refused.json()["detail"]["code"] == "audio_vide" and engine.transcriptions == []
    )


async def test_a_recording_that_weighs_too_much_is_refused_at_the_limit_of_the_setting(client, engine):
    await configure(client, stt_max_bytes=120 * 1024)

    refused = await dictate(client, WEBM + bytes(130 * 1024))
    accepted = await dictate(client, WEBM + bytes(100 * 1024))

    assert refused.status_code == 413 and refused.json()["detail"]["code"] == "fichier_trop_lourd"
    assert accepted.status_code == 200 and len(engine.transcriptions) == 1


async def test_a_recording_that_is_too_long_is_refused_by_what_the_page_says_and_for_a_wav_by_its_header(
    client, engine
):
    await configure(client, stt_max_seconds=10)

    by_page = await dictate(client, duration_seconds="13.5")
    by_header = await dictate(client, silent_wav(14.0, rate=8000), "audio/wav")
    short = await dictate(client, silent_wav(3.0, rate=8000), "audio/wav")

    assert by_page.status_code == 413 and by_page.json()["detail"]["code"] == "audio_trop_long"
    assert by_header.status_code == 413 and by_header.json()["detail"]["code"] == "audio_trop_long"
    assert short.status_code == 200 and len(engine.transcriptions) == 1


def _depends_on(dependant, target) -> bool:
    return any(sub.call is target or _depends_on(sub, target) for sub in dependant.dependencies)


def test_every_route_of_the_voice_needs_a_signed_in_person():
    routes = [route for route in voice_router.routes if hasattr(route, "dependant")]

    assert len(routes) >= 7
    assert all(_depends_on(route.dependant, get_current_user) for route in routes)


async def test_the_rate_of_a_person_is_limited_and_nothing_is_called_past_it(client, engine, monkeypatch):
    await configure(client)
    monkeypatch.setattr(voice_service._settings, "VOICE_TRANSCRIPTIONS_PER_USER_PER_MINUTE", 2)

    codes = [(await dictate(client)).status_code for _ in range(3)]
    become(BOB)
    other = (await dictate(client)).status_code

    assert codes == [200, 200, 429] and other == 200 and len(engine.transcriptions) == 3


async def test_a_rate_that_cannot_be_checked_stops_the_request_before_the_engine(client, engine, monkeypatch):
    await configure(client)

    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(voice_service, "async_redis", broken)

    refused = await dictate(client)

    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "limite_indisponible"
    assert engine.transcriptions == []


@pytest.mark.parametrize(
    "error, status, code",
    [
        (status_error(AuthenticationError, 401), 502, "cle_refusee"),
        (status_error(NotFoundError, 404), 502, "modele_introuvable"),
        (status_error(BadRequestError, 400), 502, "parametre_refuse"),
        (status_error(BadRequestError, 415), 502, "format_refuse"),
        (status_error(RateLimitError, 429), 503, "moteur_surcharge"),
        (APIConnectionError(request=None), 503, "moteur_indisponible"),
        (APITimeoutError(request=None), 504, "delai_depasse"),
        (RuntimeError(LEAK), 502, "moteur_en_erreur"),
    ],
)
async def test_an_engine_that_fails_is_named_by_a_code_and_nothing_of_its_text_reaches_the_person(
    client, engine, error, status, code
):
    await configure(client)
    engine.error = error

    refused = await dictate(client)
    refused_speech = await read_aloud(client)

    assert (refused.status_code, refused.json()["detail"]["code"]) == (status, code)
    assert refused_speech.status_code == status and refused_speech.json()["detail"]["code"] == code
    assert LEAK not in refused.text and HUB_KEY not in refused.text and LEAK not in refused_speech.text


# --- nothing is kept ---


async def test_neither_the_audio_nor_the_text_is_written_anywhere_nor_logged(client, engine, monkeypatch, logs):
    await configure(client)
    stored: list = []
    monkeypatch.setattr(storage, "put_object", lambda *args, **kwargs: stored.append(args))
    private_audio = WEBM + b"AUDIO-CONTENT-THAT-MUST-NOT-BE-KEPT"
    engine.text = "CONFIDENTIAL-WORDS-THAT-MUST-NOT-BE-LOGGED"

    response = await dictate(client, private_audio, duration_seconds="4")
    await read_aloud(client, "CONFIDENTIAL-TEXT-READ-ALOUD")

    assert response.status_code == 200 and stored == []
    joined = "".join(logs)
    assert "CONFIDENTIAL" not in joined and "AUDIO-CONTENT" not in joined
    async with async_session_factory() as session:
        columns = (await session.execute(select(TokenUsage.step, TokenUsage.model))).all()
    assert "CONFIDENTIAL" not in str(columns)


async def test_what_a_transcription_and_a_reading_cost_is_written_as_seconds_and_characters(client, engine):
    await configure(client)

    await dictate(client, duration_seconds="7.5")
    await read_aloud(client, "Bonjour à tous.")

    rows = {row.step: row for row in await usage_rows()}
    assert rows["transcription"].audio_seconds == pytest.approx(7.5) and rows["transcription"].model == "whisper-1"
    assert rows["speech"].characters == len("Bonjour à tous.") and rows["speech"].model == "tts-1"
    assert all(row.total_tokens == 0 and row.user_id == ALICE for row in rows.values())


async def test_a_transcription_is_given_even_when_its_usage_cannot_be_written(client, engine, monkeypatch):
    await configure(client)

    async def broken(self, row):
        raise RuntimeError("database is down")

    monkeypatch.setattr(TokenUsageRepository, "add", broken)

    assert (await dictate(client)).status_code == 200


# --- speech ---


async def test_a_text_is_read_by_the_engine_with_the_voice_the_format_and_no_cache(client, engine):
    await configure(client, tts_voice_en="Bella", tts_format="wav")
    engine.audio = silent_wav()

    response = await read_aloud(client, "  Bonjour \n  à tous. ", language="fr")

    assert response.status_code == 200 and response.content == engine.audio
    assert response.headers["content-type"] == "audio/wav" and response.headers["cache-control"] == "no-store"
    [call] = engine.speeches
    assert call["model"] == "tts-1" and call["voice"] == "French" and call["input"] == "Bonjour à tous."
    assert call["response_format"] == "wav"


async def test_an_answer_in_english_is_read_with_the_english_voice_when_there_is_one(client, engine):
    await configure(client, tts_voice_en="Bella")

    await read_aloud(client, "Hello there.", language="en")
    await read_aloud(client, "Hello there.", language="en-GB")
    await read_aloud(client, "Bonjour.", language="fr")
    await read_aloud(client, "Bonjour.")

    assert [call["voice"] for call in engine.speeches] == ["Bella", "Bella", "French", "French"]


async def test_without_a_voice_the_engine_is_asked_for_a_standard_one(client, engine):
    await configure(client, tts_voice="")

    await read_aloud(client)

    assert engine.speeches[0]["voice"] == "alloy"


async def test_nothing_to_read_or_too_much_is_refused_and_the_engine_is_not_called(client, engine):
    await configure(client, tts_max_chars=100)

    empty = await read_aloud(client, "   \n ")
    long = await read_aloud(client, "x" * 101)
    exact = await read_aloud(client, "x" * 100)

    assert empty.status_code == 422 and empty.json()["detail"]["code"] == "texte_vide"
    assert long.status_code == 413 and long.json()["detail"]["code"] == "texte_trop_long"
    assert exact.status_code == 200 and len(engine.speeches) == 1


@pytest.mark.parametrize("answer", [b"", b"<html>Bad gateway</html>", b"{'error': 'no'}"])
async def test_what_the_engine_gives_back_that_is_not_audio_is_refused(client, engine, answer):
    await configure(client)
    engine.audio = answer

    refused = await read_aloud(client)

    assert refused.status_code == 502 and refused.json()["detail"]["code"] == "audio_invalide"


async def test_audio_that_is_too_heavy_is_refused(client, engine, monkeypatch):
    await configure(client)
    monkeypatch.setattr(voice_service._settings, "VOICE_TTS_MAX_AUDIO_BYTES", 100)
    engine.audio = MP3

    refused = await read_aloud(client)

    assert refused.status_code == 502 and refused.json()["detail"]["code"] == "audio_invalide"


async def test_the_rate_of_readings_is_limited_too(client, engine, monkeypatch):
    await configure(client)
    monkeypatch.setattr(voice_service._settings, "VOICE_SPEECH_PER_USER_PER_MINUTE", 1)

    codes = [(await read_aloud(client)).status_code for _ in range(2)]

    assert codes == [200, 429] and len(engine.speeches) == 1


# --- the tests of an engine ---


async def test_the_test_of_transcription_sends_a_second_of_silence_and_says_what_was_measured(client, engine):
    await configure(client)
    engine.text = ""
    become(ROOT, admin=True)

    result = (await client.post("/api/admin/voice/test-transcription")).json()

    assert result["ok"] is True and result["text"] == "" and result["duration_ms"] >= 0 and result["code"] is None
    [call] = engine.transcriptions
    assert call["file"][0] == "audio.wav" and call["file"][2] == "audio/wav" and call["model"] == "whisper-1"


async def test_the_test_of_speech_says_the_type_and_the_size_of_what_was_made(client, engine):
    await configure(client)
    become(ROOT, admin=True)

    result = (await client.post("/api/admin/voice/test-speech")).json()

    assert result["ok"] is True and result["content_type"] == "audio/mpeg" and result["audio_bytes"] == len(MP3)


async def test_a_test_that_fails_gives_a_code_and_words_never_the_engines_text_nor_the_key(client, engine):
    await configure(client)
    engine.error = status_error(AuthenticationError, 401)
    become(ROOT, admin=True)

    result = await client.post("/api/admin/voice/test-transcription")

    assert result.status_code == 200
    assert result.json()["ok"] is False and result.json()["code"] == "cle_refusee"
    assert LEAK not in result.text and HUB_KEY not in result.text


async def test_the_test_of_a_function_that_is_not_complete_says_so(client, engine):
    become(ROOT, admin=True)

    result = (await client.post("/api/admin/voice/test-speech")).json()

    assert result["ok"] is False and result["code"] == "non_configuree" and engine.speeches == []
