import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import models as models_router


def _fake_openai_client(
    all_ids: list[str], *, chat_capable_ids: set[str] = frozenset(), embedding_capable_ids: set[str] = frozenset()
) -> SimpleNamespace:
    async def create_chat(model: str, **_kwargs):
        if model not in chat_capable_ids:
            raise RuntimeError(f"model '{model}' does not support chat completions")
        return SimpleNamespace()

    async def create_embedding(model: str, **_kwargs):
        if model not in embedding_capable_ids:
            raise RuntimeError(f"model '{model}' does not support embeddings")
        return SimpleNamespace()

    models_data = [SimpleNamespace(id=i) for i in all_ids]
    return SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=models_data))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create_chat))),
        embeddings=SimpleNamespace(create=AsyncMock(side_effect=create_embedding)),
    )


def test_list_models_discovers_and_caches_chat_capable_models(client, monkeypatch):
    fake_client = _fake_openai_client(
        all_ids=["gpt-4o", "mistral-small", "text-embedding-3"],
        chat_capable_ids={"gpt-4o", "mistral-small"},
    )
    monkeypatch.setattr(models_router, "_openai_client", fake_client)

    with patch("app.routers.models.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = None

        response = client.get("/api/models")

    assert response.status_code == 200
    model_ids = [m["id"] for m in response.json()["models"]]
    assert model_ids == ["gpt-4o", "mistral-small"]

    cached_key, cached_value = mock_redis.client.set.call_args[0]
    assert cached_key == models_router.CHAT_CACHE_KEY
    assert json.loads(cached_value) == ["gpt-4o", "mistral-small"]


def test_list_models_uses_cache_without_calling_the_hub(client, monkeypatch):
    fake_client = _fake_openai_client(all_ids=[])
    monkeypatch.setattr(models_router, "_openai_client", fake_client)

    with patch("app.routers.models.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = json.dumps(["cached-model"])

        response = client.get("/api/models")

    assert response.status_code == 200
    assert [m["id"] for m in response.json()["models"]] == ["cached-model"]
    fake_client.models.list.assert_not_called()


def test_list_models_returns_503_when_llm_hub_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(models_router, "_openai_client", None)

    response = client.get("/api/models")

    assert response.status_code == 503


def test_list_embedding_models_discovers_and_caches_embedding_capable_models(client, monkeypatch):
    fake_client = _fake_openai_client(
        all_ids=["gpt-4o", "text-embedding-3-small"],
        embedding_capable_ids={"text-embedding-3-small"},
    )
    monkeypatch.setattr(models_router, "_openai_client", fake_client)

    with patch("app.routers.models.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = None

        response = client.get("/api/embedding-models")

    assert response.status_code == 200
    assert [m["id"] for m in response.json()["models"]] == ["text-embedding-3-small"]

    cached_key, _ = mock_redis.client.set.call_args[0]
    assert cached_key == models_router.EMBEDDING_CACHE_KEY


def test_list_embedding_models_returns_503_when_llm_hub_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(models_router, "_openai_client", None)

    response = client.get("/api/embedding-models")

    assert response.status_code == 503
