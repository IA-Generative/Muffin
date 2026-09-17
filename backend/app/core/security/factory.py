import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.config import KeycloakSettings
from app.core.security.claims import extract_identity
from app.core.security.keycloak_client import keycloak_openid, session_store


@dataclass
class RequestContext:
    user_id: str
    email: str
    roles: list[str]
    is_admin: bool
    first_name: str = ""
    last_name: str = ""


class KeycloakToken:
    """Real verifier: a bearer access token (non-browser clients) or the BFF
    session cookie set by /api/auth/callback (browser clients)."""

    def __init__(self) -> None:
        self._keycloak_settings = KeycloakSettings()

    def __call__(self, request: Request) -> RequestContext:
        identity = self._from_bearer_token(request) or self._from_session_cookie(request)
        if identity is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return RequestContext(**identity)

    def _from_bearer_token(self, request: Request) -> dict | None:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return None
        token = authorization.removeprefix("Bearer ")
        try:
            # userinfo, not introspect: introspection requires the caller to be
            # in the token's own audience, which a resource server usually isn't.
            claims = keycloak_openid.userinfo(token)
        except Exception:
            return None
        identity = extract_identity(claims, self._keycloak_settings.KEYCLOAK_CLIENT_ID)
        return identity

    def _from_session_cookie(self, request: Request) -> dict | None:
        session_id = request.cookies.get(self._keycloak_settings.SESSION_COOKIE_NAME)
        if not session_id:
            return None
        session = session_store.get_session(session_id)
        if session is None:
            return None
        return session.identity


class AllowAllAccess:
    """Dev/test verifier: no Keycloak, no Redis - a fixed identity for every
    request. Selected via VERIFY_TOKEN_MODEL=full-access (CI unit tests)."""

    def __call__(self, request: Request) -> RequestContext:
        return RequestContext(user_id="dev-user", email="dev@example.com", roles=["admin"], is_admin=True)


SECURITY_FACTORY = {"full-access": AllowAllAccess, "keycloak": KeycloakToken}


def get_token_verifier():
    strategy = SECURITY_FACTORY[os.environ.get("VERIFY_TOKEN_MODEL", "keycloak")]
    return strategy()


TokenVerifier = get_token_verifier()


def get_current_user(request: Request) -> RequestContext:
    return TokenVerifier(request)
