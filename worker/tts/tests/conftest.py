import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import engine as engine_module
from app.config import Settings
from app.main import create_app

SAMPLE_RATE = 24000
VOICES = ["French", "FrenchTeacher", "Bella", "SpanishAbuela"]


class FakeEngine:
    """Returns half a second of a sine wave; can be made to block or to fail."""

    sample_rate = SAMPLE_RATE

    def __init__(self) -> None:
        self.voices = list(VOICES)
        self.calls: list[tuple[str, str, bool]] = []
        self.gate: threading.Event | None = None
        self.started = threading.Event()
        self.error: Exception | None = None

    def synthesize(self, text: str, voice: str, normalize: bool) -> np.ndarray:
        self.calls.append((text, voice, normalize))
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(10), "the test never released the engine"
        if self.error is not None:
            raise self.error
        t = np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE
        return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> Iterator[Callable[..., TestClient]]:
    """Builds a client on the fake engine (waits for the model to be 'loaded' unless `wait=False`)."""
    opened: list[TestClient] = []

    def factory(wait: bool = True, loader: Callable[[], object] | None = None, **overrides: object) -> TestClient:
        monkeypatch.setattr(engine_module, "get_engine", loader or (lambda: engine))
        client = TestClient(create_app(replace(Settings(), **overrides)))
        client.__enter__()
        opened.append(client)
        if wait:
            deadline = time.monotonic() + 5
            while client.get("/health").status_code != 200:
                assert time.monotonic() < deadline, "the fake engine was never loaded"
                time.sleep(0.01)
        return client

    yield factory
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
