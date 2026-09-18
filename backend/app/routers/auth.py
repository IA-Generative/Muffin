import base64
import hashlib
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KeycloakSettings
from app.core.security.claims import extract_identity
from app.core.security.factory import RequestContext, get_current_user
from app.core.security.keycloak_client import keycloak_openid, session_store
from app.core.security.session import PendingAuth
from app.core.sharing import SharingNotConfiguredError, hash_identifier, normalize_email, normalize_group
from app.db import get_db
from app.repositories.collection_repository import CollectionRepository

router = APIRouter(tags=["Auth"])

# Exposed as module attributes (rather than closed over) so tests can swap
# them out with monkeypatch.setattr without a live Keycloak or Redis.
_keycloak_settings = KeycloakSettings()
_keycloak_openid = keycloak_openid
_session_store = session_store

LOGIN_RATE_LIMIT = 20
LOGIN_RATE_WINDOW_SECONDS = 60


def _is_safe_internal_path(path: str) -> bool:
    """Rejects anything that could send the browser off-site after login
    (e.g. "//evil.com" or "https://evil.com") - only "/foo/bar" is allowed."""
    return path.startswith("/") and not path.startswith("//")


def _build_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=_keycloak_settings.SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=_keycloak_settings.SESSION_COOKIE_SECURE,
        samesite=_keycloak_settings.SESSION_COOKIE_SAMESITE,
        max_age=_keycloak_settings.SESSION_TTL_SECONDS,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_keycloak_settings.SESSION_COOKIE_NAME)


async def _resolve_pending_shares(db: AsyncSession, identity: dict) -> None:
    """Promotes any PENDING collection share invited under this identity's email or groups to
    ACTIVE - passive resolution, never a lookup the owner who created the invitation (or anyone
    else) can trigger or observe. See app/core/sharing.py. Best-effort: a login must never fail
    because of this, so any error here is logged and swallowed rather than surfaced to the caller."""
    try:
        repository = CollectionRepository(db)
        if identity.get("email"):
            await repository.resolve_pending_user_shares(
                hash_identifier(normalize_email(identity["email"])), identity["user_id"]
            )
        for group in identity.get("groups") or []:
            await repository.resolve_pending_group_shares(hash_identifier(normalize_group(group)), group)
        await db.commit()
    except SharingNotConfiguredError:
        pass
    except Exception:
        logger.exception("Failed to resolve pending collection shares at login")
        await db.rollback()


@router.get("/login", summary="Redirect the browser to Keycloak's login page")
async def login(request: Request, redirect: str = "/") -> RedirectResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _session_store.check_rate_limit(f"login:{client_ip}", LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    next_path = redirect if _is_safe_internal_path(redirect) else "/"
    code_verifier, code_challenge = _build_pkce_pair()
    state = secrets.token_urlsafe(32)
    _session_store.save_pending(state, PendingAuth(code_verifier=code_verifier, next_path=next_path))

    # Built by hand against the browser-facing public_url: keycloak_openid's
    # own auth_url() resolves against the backend-internal KEYCLOAK_URL, which
    # the browser (unlike the backend) usually cannot reach.
    query = urlencode(
        {
            "client_id": _keycloak_settings.KEYCLOAK_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": _keycloak_settings.callback_url,
            "scope": "openid profile email",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    realm_auth_endpoint = (
        f"{_keycloak_settings.public_url}/realms/{_keycloak_settings.KEYCLOAK_REALM}/protocol/openid-connect/auth"
    )
    auth_url = f"{realm_auth_endpoint}?{query}"
    return RedirectResponse(url=auth_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback", summary="Exchange the Keycloak authorization code for a session")
async def callback(code: str, state: str, db: Annotated[AsyncSession, Depends(get_db)]) -> RedirectResponse:
    pending = _session_store.pop_pending(state)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired login attempt")

    try:
        token_response = _keycloak_openid.token(
            grant_type="authorization_code",
            code=code,
            redirect_uri=_keycloak_settings.callback_url,
            code_verifier=pending.code_verifier,
        )
        claims = _keycloak_openid.userinfo(token_response["access_token"])
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Login failed") from error

    identity = extract_identity(claims, _keycloak_settings.KEYCLOAK_CLIENT_ID)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not resolve identity")

    # Every browser login is the one moment a pending collection-share invitation (by email or by
    # one of this identity's groups) can be resolved to ACTIVE - see app/core/sharing.py.
    await _resolve_pending_shares(db, identity)

    session_id = _session_store.create_session(identity, token_response)
    response = RedirectResponse(
        url=f"{_keycloak_settings.FRONTEND_URL}{pending.next_path}",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    _set_session_cookie(response, session_id)
    return response


@router.post("/token", summary="Password grant for non-browser clients (scripts, SDK)")
async def token(username: str, password: str) -> dict:
    try:
        return _keycloak_openid.token(grant_type="password", username=username, password=password)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from error


@router.post("/refresh", summary="Refresh grant for non-browser clients (scripts, SDK)")
async def refresh(refresh_token: str) -> dict:
    try:
        return _keycloak_openid.refresh_token(refresh_token)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from error


@router.post("/logout", summary="End the BFF session and the Keycloak SSO session")
async def logout(request: Request, response: Response) -> dict:
    session_id = request.cookies.get(_keycloak_settings.SESSION_COOKIE_NAME)
    id_token: str | None = None
    if session_id:
        session = _session_store.get_session(session_id)
        if session:
            id_token = session.id_token
            try:
                _keycloak_openid.logout(session.refresh_token)
            except Exception:
                pass
        _session_store.delete_session(session_id)

    _clear_session_cookie(response)
    # id_token_hint proves this /logout call isn't a forged cross-site request,
    # which is what lets Keycloak redirect straight back instead of stopping
    # on its own "do you want to log out?" confirmation page.
    query = urlencode(
        {
            "client_id": _keycloak_settings.KEYCLOAK_CLIENT_ID,
            "post_logout_redirect_uri": _keycloak_settings.FRONTEND_URL,
            **({"id_token_hint": id_token} if id_token else {}),
        }
    )
    end_session_url = (
        f"{_keycloak_settings.public_url}/realms/{_keycloak_settings.KEYCLOAK_REALM}"
        f"/protocol/openid-connect/logout?{query}"
    )
    return {"redirectUrl": end_session_url}


@router.get("/me", summary="Return the current user's profile")
async def me(user: Annotated[RequestContext, Depends(get_current_user)]) -> RequestContext:
    return user
