"""What an administrator sees of the stored secrets, and the rewrap that follows a rotation of the key (#521)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core import secret_store
from app.core.secret_store import LocalProvider, SecretsNotConfiguredError, SecretUnavailableError
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.stored_secret import StoredSecret
from app.services.secret_store_service import SecretStore

SECRET = "sk-a-long-key-of-a-service-1234567890"


def _user(is_admin: bool):
    def override() -> RequestContext:
        return RequestContext(user_id="root", email="root@example.test", roles=[], is_admin=is_admin)

    return override


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k1", bytes([1]) * 32)]))
    app.dependency_overrides[get_current_user] = _user(True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(StoredSecret))
        await session.commit()


async def _store(count: int, provider: LocalProvider) -> None:
    async with async_session_factory() as db:
        for index in range(count):
            await SecretStore(db, provider).put(
                owner="alice", purpose="transcription.api_key", plaintext=f"{SECRET}-{index}", created_by="root"
            )
        await db.commit()


async def test_an_administrator_sees_where_the_secrets_are_and_how_many_are_on_which_key(client):
    await _store(2, LocalProvider([("k1", bytes([1]) * 32)]))

    body = (await client.get("/api/admin/secrets/status")).json()

    assert body == {"provider": "local", "reachable": True, "current_version": "k1", "versions": {"k1": 2}, "stale": 0}


async def test_after_a_rotation_the_status_counts_what_a_rewrap_has_left(client, monkeypatch):
    await _store(3, LocalProvider([("k1", bytes([1]) * 32)]))
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k2", bytes([2]) * 32), ("k1", bytes([1]) * 32)]))

    assert (await client.get("/api/admin/secrets/status")).json()["stale"] == 3
    rewrapped = (await client.post("/api/admin/secrets/rewrap?limit=2")).json()
    assert rewrapped == {"rewrapped": 2, "remaining": 1, "current_version": "k2"}
    status = (await client.get("/api/admin/secrets/status")).json()
    assert status["versions"] == {"k1": 1, "k2": 2} and status["stale"] == 1
    assert (await client.post("/api/admin/secrets/rewrap")).json()["remaining"] == 0


async def test_no_answer_of_the_admin_routes_shows_a_secret_or_a_ciphertext(client):
    await _store(1, LocalProvider([("k1", bytes([1]) * 32)]))

    for response in (await client.get("/api/admin/secrets/status"), await client.post("/api/admin/secrets/rewrap")):
        assert SECRET not in response.text
        assert "local:k1:" not in response.text


async def test_a_provider_that_cannot_be_reached_is_reported_not_raised(client, monkeypatch):
    class Down:
        name = "vault"

        async def current_version(self):
            raise SecretUnavailableError("Vault cannot be reached")

    await _store(2, LocalProvider([("k1", bytes([1]) * 32)]))
    monkeypatch.setattr(secret_store, "_provider", Down())

    response = await client.get("/api/admin/secrets/status")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "unavailable",
        "reachable": False,
        "current_version": None,
        "versions": {"k1": 2},
        "stale": 2,
    }
    assert (await client.post("/api/admin/secrets/rewrap")).status_code == 503


async def test_a_deployment_with_no_key_reports_it_and_cannot_rewrap(client, monkeypatch):
    def no_key(_settings):
        raise SecretsNotConfiguredError("No local key is set")

    monkeypatch.setattr(secret_store, "_provider", None)
    monkeypatch.setattr(secret_store, "build_provider", no_key)

    status = await client.get("/api/admin/secrets/status")

    assert status.status_code == 200 and status.json()["reachable"] is False
    assert (await client.post("/api/admin/secrets/rewrap")).status_code == 503


async def test_who_is_not_an_administrator_sees_nothing(client):
    app.dependency_overrides[get_current_user] = _user(False)

    assert (await client.get("/api/admin/secrets/status")).status_code == 403
    assert (await client.post("/api/admin/secrets/rewrap")).status_code == 403
