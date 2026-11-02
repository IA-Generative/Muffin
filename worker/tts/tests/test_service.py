import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeEngine

URL = "/v1/audio/speech"
SECRET_TEXT = "Le mot de passe est ornithorynque-42."


def speak(client: TestClient, text: str = "Bonjour.", **headers: str):
    return client.post(URL, json={"input": text}, headers=headers)


def test_health_is_503_while_the_model_loads_then_200(make_client, engine: FakeEngine):
    release = threading.Event()

    def slow_loader() -> FakeEngine:
        assert release.wait(10)
        return engine

    client = make_client(wait=False, loader=slow_loader)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "loading"}
    assert speak(client).status_code == 503
    assert speak(client).headers["retry-after"]

    release.set()
    deadline = time.monotonic() + 5
    while client.get("/health").status_code != 200:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert client.get("/health").json() == {"status": "ok"}


def test_health_reports_a_failed_load(make_client):
    def broken() -> FakeEngine:
        raise FileNotFoundError("no model")

    client = make_client(wait=False, loader=broken)
    deadline = time.monotonic() + 5
    while client.get("/health").json()["status"] == "loading":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert client.get("/health").status_code == 503
    assert client.get("/health").json() == {"status": "failed"}


def test_a_default_voice_the_model_lacks_fails_the_load(make_client):
    client = make_client(wait=False, default_voice="Klingon")
    deadline = time.monotonic() + 5
    while client.get("/health").json()["status"] == "loading":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert client.get("/health").json() == {"status": "failed"}


def test_open_when_no_key_is_set(client: TestClient):
    assert speak(client).status_code == 200
    assert client.get("/v1/models").status_code == 200


def test_key_is_required_on_v1_routes_but_not_on_health(make_client):
    client = make_client(api_key="s3cret")
    assert client.get("/health").status_code == 200
    for response in (speak(client), client.get("/v1/models"), client.get("/v1/audio/voices")):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_api_key"
        assert response.headers["www-authenticate"] == "Bearer"
    assert speak(client, Authorization="Bearer wrong").status_code == 401
    assert speak(client, Authorization="s3cret").status_code == 401
    assert speak(client, Authorization="Bearer s3cret").status_code == 200
    assert client.get("/v1/models", headers={"Authorization": "bearer s3cret"}).status_code == 200


def test_429_when_every_slot_is_busy(make_client, engine: FakeEngine):
    engine.gate = threading.Event()
    client = make_client(max_concurrency=1)
    first: dict[str, int] = {}
    worker = threading.Thread(target=lambda: first.update(status=speak(client).status_code))
    worker.start()
    assert engine.started.wait(5)

    started = time.monotonic()
    busy = speak(client)
    assert busy.status_code == 429
    assert time.monotonic() - started < 1  # answered at once, no queue
    assert int(busy.headers["retry-after"]) > 0
    assert busy.json()["error"]["code"] == "busy"

    engine.gate.set()
    worker.join(5)
    assert first == {"status": 200}
    assert speak(client).status_code == 200


def test_two_slots_run_two_syntheses(make_client, engine: FakeEngine):
    engine.gate = threading.Event()
    client = make_client(max_concurrency=2)
    statuses: list[int] = []
    workers = [threading.Thread(target=lambda: statuses.append(speak(client).status_code)) for _ in range(2)]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + 5
    while len(engine.calls) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert speak(client).status_code == 429
    engine.gate.set()
    for worker in workers:
        worker.join(5)
    assert statuses == [200, 200]


def test_504_on_timeout_and_the_slot_stays_taken_until_the_work_ends(make_client, engine: FakeEngine):
    engine.gate = threading.Event()
    client = make_client(request_timeout_seconds=0.2)
    response = speak(client)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"
    # The model call cannot be interrupted: it still holds the slot.
    assert speak(client).status_code == 429
    engine.gate.set()
    deadline = time.monotonic() + 5
    while (status := speak(client).status_code) == 429:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert status == 200


def test_the_text_is_never_logged(client: TestClient, engine: FakeEngine, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    assert speak(client, SECRET_TEXT).status_code == 200
    engine.error = RuntimeError(f"failed on {SECRET_TEXT}")
    assert speak(client, SECRET_TEXT).status_code == 500
    assert client.post(URL, json={"input": SECRET_TEXT, "voice": "nope"}).status_code == 422
    assert "ornithorynque" not in caplog.text
    assert "chars=" in caplog.text  # the lengths are
