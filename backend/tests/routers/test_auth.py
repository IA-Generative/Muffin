from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

from app.core.security.session import PendingAuth
from app.routers import auth as auth_router


def test_login_redirects_to_keycloak_with_pkce_params(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = True
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = client.get("/api/auth/login", params={"redirect": "/collections"}, follow_redirects=False)

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


def test_login_rejects_open_redirect_and_falls_back_to_root(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = True
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    client.get("/api/auth/login", params={"redirect": "https://evil.example"}, follow_redirects=False)

    _, saved_pending = mock_store.save_pending.call_args[0]
    assert saved_pending.next_path == "/"


def test_login_is_rate_limited(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.check_rate_limit.return_value = False
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 429


def test_callback_creates_session_and_redirects(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.pop_pending.return_value = PendingAuth(code_verifier="verifier", next_path="/collections")
    mock_store.create_session.return_value = "new-session-id"
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    mock_openid = MagicMock()
    mock_openid.token.return_value = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    mock_openid.userinfo.return_value = {"sub": "u1", "email": "a@b.c"}
    monkeypatch.setattr(auth_router, "_keycloak_openid", mock_openid)

    response = client.get("/api/auth/callback", params={"code": "abc", "state": "xyz"}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"{auth_router._keycloak_settings.FRONTEND_URL}/collections"
    assert auth_router._keycloak_settings.SESSION_COOKIE_NAME in response.cookies


def test_callback_rejects_unknown_state(client, monkeypatch):
    mock_store = MagicMock()
    mock_store.pop_pending.return_value = None
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = client.get("/api/auth/callback", params={"code": "abc", "state": "unknown"})

    assert response.status_code == 400


def test_logout_clears_session_and_returns_keycloak_redirect_url(client, monkeypatch):
    mock_store = MagicMock()
    fake_session = MagicMock(refresh_token="rt")
    mock_store.get_session.return_value = fake_session
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    mock_openid = MagicMock()
    monkeypatch.setattr(auth_router, "_keycloak_openid", mock_openid)

    client.cookies.set(auth_router._keycloak_settings.SESSION_COOKIE_NAME, "session-id-123")
    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert "redirectUrl" in response.json()
    mock_openid.logout.assert_called_once_with("rt")
    mock_store.delete_session.assert_called_once_with("session-id-123")


def test_logout_without_a_session_still_succeeds(client, monkeypatch):
    mock_store = MagicMock()
    monkeypatch.setattr(auth_router, "_session_store", mock_store)

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    mock_store.delete_session.assert_not_called()


def test_me_returns_the_dev_identity_under_full_access_mode(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user_id"] == "dev-user"
