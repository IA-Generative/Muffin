import app.graph.services.prompts as prompts_module
from app.graph.services.prompts import get_prompt


class _FakeBackendClient:
    def __init__(self, prompt: dict | None = None) -> None:
        self.prompt = prompt
        self.calls = 0

    def get_active_prompt(self, name: str) -> dict | None:
        self.calls += 1
        return self.prompt


def _patch(monkeypatch, fake) -> None:
    monkeypatch.setattr(prompts_module, "backend_client", fake)
    prompts_module._cache.clear()


def test_returns_fallback_when_no_active_prompt(monkeypatch):
    _patch(monkeypatch, _FakeBackendClient(prompt=None))
    content, version_id = get_prompt("generate_answer", fallback="the fallback text")
    assert content == "the fallback text"
    assert version_id is None


def test_returns_active_prompt_when_available(monkeypatch):
    fake = _FakeBackendClient(prompt={"id": "v-1", "name": "generate_answer", "version": 3, "content": "db content"})
    _patch(monkeypatch, fake)
    content, version_id = get_prompt("generate_answer", fallback="the fallback text")
    assert content == "db content"
    assert version_id == "v-1"


def test_caches_within_ttl(monkeypatch):
    fake = _FakeBackendClient(prompt={"id": "v-1", "name": "generate_answer", "version": 1, "content": "db content"})
    _patch(monkeypatch, fake)
    get_prompt("generate_answer", fallback="fallback")
    get_prompt("generate_answer", fallback="fallback")
    assert fake.calls == 1


def test_cache_expires_after_ttl(monkeypatch):
    fake = _FakeBackendClient(prompt={"id": "v-1", "name": "generate_answer", "version": 1, "content": "db content"})
    _patch(monkeypatch, fake)
    monkeypatch.setattr(prompts_module, "_CACHE_TTL_SECONDS", 0)
    get_prompt("generate_answer", fallback="fallback")
    get_prompt("generate_answer", fallback="fallback")
    assert fake.calls == 2
