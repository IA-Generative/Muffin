import time

from app.core.security.session import PendingAuth


def test_save_and_pop_pending_round_trips(session_store):
    pending = PendingAuth(code_verifier="verifier-123", next_path="/collections")
    session_store.save_pending("state-abc", pending)

    result = session_store.pop_pending("state-abc")

    assert result == pending


def test_pop_pending_is_single_use(session_store):
    session_store.save_pending("state-abc", PendingAuth(code_verifier="v", next_path="/"))

    session_store.pop_pending("state-abc")

    assert session_store.pop_pending("state-abc") is None


def test_pop_pending_unknown_state_returns_none(session_store):
    assert session_store.pop_pending("never-saved") is None


def test_create_and_get_session_round_trips(session_store):
    identity = {"user_id": "u1", "email": "a@b.c", "roles": [], "is_admin": False}
    token_response = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    session_id = session_store.create_session(identity, token_response)
    session = session_store.get_session(session_id)

    assert session is not None
    assert session.identity == identity
    assert session.access_token == "at"


def test_get_session_unknown_id_returns_none(session_store):
    assert session_store.get_session("does-not-exist") is None


def test_get_session_refreshes_when_close_to_expiry(session_store, mock_keycloak_openid):
    identity = {"user_id": "u1", "email": "a@b.c", "roles": [], "is_admin": False}
    # expires_in=10 with a 30s margin: already due for a refresh on the very next read.
    token_response = {"access_token": "old-at", "refresh_token": "old-rt", "expires_in": 10}
    session_id = session_store.create_session(identity, token_response)

    mock_keycloak_openid.refresh_token.return_value = {
        "access_token": "new-at",
        "refresh_token": "new-rt",
        "expires_in": 3600,
    }

    session = session_store.get_session(session_id)

    assert session.access_token == "new-at"
    mock_keycloak_openid.refresh_token.assert_called_once_with("old-rt")


def test_get_session_deletes_session_when_refresh_fails(session_store, mock_keycloak_openid):
    identity = {"user_id": "u1", "email": "a@b.c", "roles": [], "is_admin": False}
    token_response = {"access_token": "old-at", "refresh_token": "old-rt", "expires_in": 10}
    session_id = session_store.create_session(identity, token_response)
    mock_keycloak_openid.refresh_token.side_effect = Exception("refresh token expired")

    session = session_store.get_session(session_id)

    assert session is None
    assert session_store.get_session(session_id) is None


def test_delete_session_removes_it(session_store):
    identity = {"user_id": "u1", "email": "a@b.c", "roles": [], "is_admin": False}
    token_response = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    session_id = session_store.create_session(identity, token_response)

    session_store.delete_session(session_id)

    assert session_store.get_session(session_id) is None


def test_check_rate_limit_allows_up_to_the_limit(session_store):
    for _ in range(5):
        assert session_store.check_rate_limit("key", limit=5, window_seconds=60) is True

    assert session_store.check_rate_limit("key", limit=5, window_seconds=60) is False


def test_check_rate_limit_uses_independent_keys(session_store):
    assert session_store.check_rate_limit("key-a", limit=1, window_seconds=60) is True
    assert session_store.check_rate_limit("key-b", limit=1, window_seconds=60) is True
    assert session_store.check_rate_limit("key-a", limit=1, window_seconds=60) is False


def test_session_expires_at_is_in_the_future(session_store):
    identity = {"user_id": "u1", "email": "a@b.c", "roles": [], "is_admin": False}
    token_response = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    before = time.time()

    session_id = session_store.create_session(identity, token_response)
    session = session_store.get_session(session_id)

    assert session.expires_at > before
