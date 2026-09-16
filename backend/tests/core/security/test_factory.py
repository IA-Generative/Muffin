from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security.factory import AllowAllAccess, KeycloakToken, RequestContext, get_token_verifier


def make_request(headers: dict | None = None, cookies: dict | None = None):
    request = MagicMock()
    request.headers = headers or {}
    request.cookies = cookies or {}
    return request


def test_allow_all_access_returns_a_fixed_admin_identity():
    verifier = AllowAllAccess()

    context = verifier(make_request())

    assert isinstance(context, RequestContext)
    assert context.is_admin is True


@pytest.mark.parametrize(
    ("env_value", "expected_type"),
    [("full-access", AllowAllAccess), ("keycloak", KeycloakToken), (None, KeycloakToken)],
)
def test_get_token_verifier_selects_strategy_from_env(monkeypatch, env_value, expected_type):
    if env_value is None:
        monkeypatch.delenv("VERIFY_TOKEN_MODEL", raising=False)
    else:
        monkeypatch.setenv("VERIFY_TOKEN_MODEL", env_value)

    assert isinstance(get_token_verifier(), expected_type)


class TestKeycloakToken:
    def test_accepts_a_valid_bearer_token(self):
        verifier = KeycloakToken()
        request = make_request(headers={"Authorization": "Bearer good-token"})

        with patch("app.core.security.factory.keycloak_openid") as mock_openid:
            mock_openid.userinfo.return_value = {"sub": "u1", "email": "a@b.c"}
            context = verifier(request)

        assert context.user_id == "u1"
        mock_openid.userinfo.assert_called_once_with("good-token")

    def test_rejects_an_invalid_bearer_token_and_falls_back_to_cookie(self):
        verifier = KeycloakToken()
        request = make_request(headers={"Authorization": "Bearer bad-token"})

        with patch("app.core.security.factory.keycloak_openid") as mock_openid:
            mock_openid.userinfo.side_effect = Exception("token expired")
            with pytest.raises(HTTPException) as exc_info:
                verifier(request)

        assert exc_info.value.status_code == 401

    def test_accepts_a_valid_session_cookie(self):
        verifier = KeycloakToken()
        request = make_request(cookies={"muffin_session": "session-id-123"})
        fake_session = MagicMock(identity={"user_id": "u2", "email": "x@y.z", "roles": [], "is_admin": False})

        with patch("app.core.security.factory.session_store") as mock_store:
            mock_store.get_session.return_value = fake_session
            context = verifier(request)

        assert context.user_id == "u2"

    def test_rejects_when_nothing_is_present(self):
        verifier = KeycloakToken()
        request = make_request()

        with pytest.raises(HTTPException) as exc_info:
            verifier(request)

        assert exc_info.value.status_code == 401
