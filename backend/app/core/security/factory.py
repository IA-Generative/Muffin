import os
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KeycloakSettings
from app.core.security.claims import extract_identity
from app.core.security.keycloak_client import keycloak_openid, session_store
from app.db import get_db
from app.repositories.group_repository import GroupRepository


@dataclass
class RequestContext:
    user_id: str
    email: str
    roles: list[str]
    is_admin: bool
    first_name: str = ""
    last_name: str = ""
    groups: list[str] = field(default_factory=list)
    # The user's own access token, for the tools that call a service on their behalf (see app/agent/user_token.py): kept
    # out of every repr and log, and never stored.
    access_token: str | None = field(default=None, repr=False)


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
        return {**identity, "access_token": token}

    def _from_session_cookie(self, request: Request) -> dict | None:
        session_id = request.cookies.get(self._keycloak_settings.SESSION_COOKIE_NAME)
        if not session_id:
            return None
        session = session_store.get_session(session_id)
        if session is None:
            return None
        return {**session.identity, "access_token": session.access_token}


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

# Declared purely so Swagger UI shows an "Authorize" button and lets a bearer
# token be tested from /api/docs - the actual token extraction/verification
# still happens inside KeycloakToken._from_bearer_token above, unaffected by
# this dependency. auto_error=False: a request with no/invalid Authorization
# header must still be able to fall through to the BFF session cookie below,
# never get rejected here before that check runs.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Keycloak access token. Browser clients authenticate via the BFF session "
    "cookie instead - this is only for testing endpoints directly from Swagger UI.",
)
_bearer_security = Security(bearer_scheme)
_db_dependency = Depends(get_db)


def get_token_identity(
    request: Request, _credentials: HTTPAuthorizationCredentials | None = _bearer_security
) -> RequestContext:
    """Who is asking according to their token alone - what get_current_user starts from."""
    return TokenVerifier(request)


_identity_dependency = Depends(get_token_identity)


async def get_current_user(
    context: RequestContext = _identity_dependency,
    db: AsyncSession = _db_dependency,
) -> RequestContext:
    """Who is asking, with the groups of their token plus the ones they are a member of in Muffin (#453) -
    so that a share to either reaches them, and so does what snapshots `groups` (a run's `user_groups`)."""
    context.groups = list(dict.fromkeys([*context.groups, *await GroupRepository(db).group_ids_of(context.user_id)]))
    return context
