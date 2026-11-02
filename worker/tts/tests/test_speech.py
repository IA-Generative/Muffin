import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from tests.conftest import SAMPLE_RATE, FakeEngine

URL = "/v1/audio/speech"


def post(client: TestClient, **body: object):
    return client.post(URL, json={"model": "kitten-tts-2", "input": "Bonjour tout le monde.", **body})


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert set(error) == {"message", "type", "code"}


def test_default_is_wav_with_the_default_voice(client: TestClient, engine: FakeEngine):
    response = post(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert engine.calls == [("Bonjour tout le monde.", "French", False)]
    samples, rate = sf.read(io.BytesIO(response.content))
    assert rate == SAMPLE_RATE and len(samples) == SAMPLE_RATE // 2


@pytest.mark.parametrize(
    ("fmt", "media_type"),
    [("wav", "audio/wav"), ("flac", "audio/flac"), ("mp3", "audio/mpeg"), ("pcm", "audio/pcm")],
)
def test_each_format_has_its_magic_bytes_and_content_type(client: TestClient, fmt: str, media_type: str):
    response = post(client, response_format=fmt)
    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    body = response.content
    if fmt == "wav":
        assert body[:4] == b"RIFF"
    elif fmt == "flac":
        assert body[:4] == b"fLaC"
    elif fmt == "mp3":
        assert body[:3] == b"ID3" or (body[0] == 0xFF and body[1] & 0xE0 == 0xE0)
    else:
        assert len(body) == SAMPLE_RATE // 2 * 2  # 16-bit mono
        assert np.abs(np.frombuffer(body, dtype="<i2")).max() > 5000


def test_format_name_is_case_insensitive(client: TestClient):
    assert post(client, response_format="FLAC").content[:4] == b"fLaC"


@pytest.mark.parametrize("fmt", ["opus", "aac", "ogg"])
def test_unknown_format_is_rejected(client: TestClient, fmt: str):
    assert_error(post(client, response_format=fmt), 422, "unsupported_response_format")


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_input_is_rejected(client: TestClient, text: str):
    assert_error(post(client, input=text), 422, "input_empty")


def test_missing_input_is_an_openai_style_422(client: TestClient):
    response = client.post(URL, json={"model": "kitten-tts-2"})
    assert response.status_code == 422
    assert "input" in response.json()["error"]["message"]
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_not_json_is_a_422(client: TestClient):
    response = client.post(URL, content=b"hello", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert "error" in response.json()


def test_too_long_input_is_a_413(make_client):
    client = make_client(max_chars=10)
    assert post(client, input="x" * 10).status_code == 200
    assert_error(post(client, input="x" * 11), 413, "input_too_long")


def test_voice_is_matched_case_insensitively(client: TestClient, engine: FakeEngine):
    assert post(client, voice="frenchteacher").status_code == 200
    assert post(client, voice="BELLA").status_code == 200
    assert [call[1] for call in engine.calls] == ["FrenchTeacher", "Bella"]


def test_unknown_voice_gives_the_count_not_the_list(client: TestClient):
    response = post(client, voice="alloy")
    assert_error(response, 422, "unknown_voice")
    message = response.json()["error"]["message"]
    assert "4 voices" in message
    assert "SpanishAbuela" not in message


def test_normalizer_only_for_english_voices(client: TestClient, engine: FakeEngine):
    post(client, voice="Bella")
    post(client, voice="SpanishAbuela")
    assert [call[2] for call in engine.calls] == [True, False]


@pytest.mark.parametrize("speed", [0.49, 2.01, 0, -1])
def test_speed_out_of_range_is_rejected(client: TestClient, speed: float):
    assert_error(post(client, speed=speed), 422, "invalid_speed")


def test_speed_changes_the_duration(client: TestClient):
    normal = len(post(client, response_format="pcm").content)
    fast = len(post(client, response_format="pcm", speed=2.0).content)
    slow = len(post(client, response_format="pcm", speed=0.5).content)
    assert fast == pytest.approx(normal / 2, rel=0.1)
    assert slow == pytest.approx(normal * 2, rel=0.1)


def test_unknown_fields_and_any_model_are_accepted(client: TestClient):
    response = post(client, model="tts-1-hd", instructions="whisper", stream_format="audio")
    assert response.status_code == 200


def test_engine_failure_is_a_500_without_details(client: TestClient, engine: FakeEngine):
    engine.error = RuntimeError("secret detail")
    response = post(client)
    assert_error(response, 500, "synthesis_failed")
    assert "secret detail" not in response.text


def test_models_and_voices_listings(client: TestClient):
    models = client.get("/v1/models").json()
    assert models["object"] == "list"
    assert [m["id"] for m in models["data"]] == ["kitten-tts-2"]
    voices = client.get("/v1/audio/voices").json()
    assert voices["voices"] == sorted(["French", "FrenchTeacher", "Bella", "SpanishAbuela"])
    assert voices["default"] == "French"
