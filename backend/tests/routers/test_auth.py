from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security.session import PendingAuth
from app.main import app
from app.routers import auth as auth_router


@pytest.fixture
async def client():
    # AsyncClient, not the sync TestClient: /callback now resolves a real get_db dependency (see
    # _resolve_pending_shares), and asyncpg connections from the app's pooled engine can't be
    # reused across the sync client's per-request event loops - see test_collections.py's client
    # fixture for the same reasoning against a DB-backed router.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


async def test_login_redirects_to_keycloak_with_pkce_params(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = True
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = await client.get("/api/auth/login", params={"redirect": "/collections"}, follow_redirects=False)

    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert query["client_id"] == [auth_router._keycloak_settings.KEYCLOAK_CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert "/protocol/openid-connect/auth" in location.path

    saved_state, saved_pending = mock_store.save_pending.call_args[0]
    assert saved_pending.next_path == "/collections"
    assert saved_state == query["state"][0]


async def test_login_rejects_open_redirect_and_falls_back_to_root(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = True
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    await client.get("/api/auth/login", params={"redirect": "https://evil.example"}, follow_redirects=False)

    _, saved_pending = mock_store.save_pending.call_args[0]
    assert saved_pending.next_path == "/"


async def test_login_is_rate_limited(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = False
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = await client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 429


async def test_callback_creates_session_and_redirects(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.pop_pending.return_value = PendingAuth(code_verifier="verifier", next_path="/collections")
    mock_store.create_session.return_value = "new-session-id"
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    mock_openid = MagicMock()
    mock_openid.token.return_value = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    mock_openid.userinfo.return_value = {"sub": "u1", "email": "a@b.c"}
    monkeypatch.setattr(auth_router, "_keycloak_openid", mock_openid)

    response = await client.get("/api/auth/callback", params={"code": "abc", "state": "xyz"}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"{auth_router._keycloak_settings.FRONTEND_URL}/collections"
    assert auth_router._keycloak_settings.SESSION_COOKIE_NAME in response.cookies


async def test_callback_resolves_pending_shares_for_the_logged_in_identity(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.pop_pending.return_value = PendingAuth(code_verifier="verifier", next_path="/collections")
    mock_store.create_session.return_value = "new-session-id"
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    mock_openid = MagicMock()
    mock_openid.token.return_value = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    mock_openid.userinfo.return_value = {"sub": "julie-sub", "email": "julie@example.com"}
    monkeypatch.setattr(auth_router, "_keycloak_openid", mock_openid)

    mock_repository = MagicMock()
    mock_repository.resolve_pending_user_shares = AsyncMock()
    monkeypatch.setattr(auth_router, "CollectionRepository", lambda db: mock_repository)

    response = await client.get("/api/auth/callback", params={"code": "abc", "state": "xyz"}, follow_redirects=False)

    assert response.status_code == 307
    mock_repository.resolve_pending_user_shares.assert_called_once()


async def test_callback_rejects_unknown_state(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.pop_pending.return_value = None
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = await client.get("/api/auth/callback", params={"code": "abc", "state": "unknown"})

    assert response.status_code == 400


async def test_logout_clears_session_and_returns_keycloak_redirect_url(client, monkeypatch):
    mock_store = MagicMock()
    fake_session = MagicMock(refresh_token="rt")
    mock_store.get_session.return_value = fake_session
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    mock_openid = MagicMock()
    monkeypatch.setattr(auth_router, "_keycloak_openid", mock_openid)

    client.cookies.set(auth_router._keycloak_settings.SESSION_COOKIE_NAME, "session-id-123")
    response = await client.post("/api/auth/logout")

    assert response.status_code == 200
    assert "redirectUrl" in response.json()
    mock_openid.logout.assert_called_once_with("rt")
    mock_store.delete_session.assert_called_once_with("session-id-123")


async def test_logout_without_a_session_still_succeeds(client, monkeypatch):
    mock_store = MagicMock()
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = await client.post("/api/auth/logout")

    assert response.status_code == 200
    mock_store.delete_session.assert_not_called()


async def test_me_returns_the_dev_identity_under_full_access_mode(client):
    response = await client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user_id"] == "dev-user"
