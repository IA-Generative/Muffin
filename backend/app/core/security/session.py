import json
import secrets
import time
from dataclasses import asdict, dataclass

from keycloak import KeycloakOpenID
from redis import Redis

PENDING_PREFIX = "muffin:auth:pending:"
SESSION_PREFIX = "muffin:auth:session:"
RATE_LIMIT_PREFIX = "muffin:auth:rate:"
PENDING_TTL_SECONDS = 600
# Refresh the access token this many seconds before it actually expires, so a
# request never races a token that dies mid-flight.
REFRESH_MARGIN_SECONDS = 30


@dataclass
class PendingAuth:
    code_verifier: str
    next_path: str


@dataclass
class Session:
    identity: dict
    access_token: str
    refresh_token: str
    expires_at: float


class SessionStore:
    def __init__(self, redis_client: Redis, keycloak_openid: KeycloakOpenID, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._keycloak_openid = keycloak_openid
        self._ttl_seconds = ttl_seconds

    def save_pending(self, state: str, pending: PendingAuth) -> None:
        self._redis.set(f"{PENDING_PREFIX}{state}", json.dumps(asdict(pending)), ex=PENDING_TTL_SECONDS)

    def pop_pending(self, state: str) -> PendingAuth | None:
        key = f"{PENDING_PREFIX}{state}"
        raw = self._redis.getdel(key)
        if not raw:
            return None
        return PendingAuth(**json.loads(raw))

    def create_session(self, identity: dict, token_response: dict) -> str:
        session_id = secrets.token_urlsafe(32)
        session = Session(
            identity=identity,
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            expires_at=time.time() + token_response["expires_in"],
        )
        self._redis.set(f"{SESSION_PREFIX}{session_id}", json.dumps(asdict(session)), ex=self._ttl_seconds)
        return session_id

    def get_session(self, session_id: str) -> Session | None:
        raw = self._redis.get(f"{SESSION_PREFIX}{session_id}")
        if not raw:
            return None

        session = Session(**json.loads(raw))
        if session.expires_at - REFRESH_MARGIN_SECONDS > time.time():
            return session

        return self._refresh_session(session_id, session)

    def _refresh_session(self, session_id: str, session: Session) -> Session | None:
        try:
            token_response = self._keycloak_openid.refresh_token(session.refresh_token)
        except Exception:
            self.delete_session(session_id)
            return None

        session.access_token = token_response["access_token"]
        session.refresh_token = token_response["refresh_token"]
        session.expires_at = time.time() + token_response["expires_in"]
        self._redis.set(f"{SESSION_PREFIX}{session_id}", json.dumps(asdict(session)), ex=self._ttl_seconds)
        return session

    def delete_session(self, session_id: str) -> None:
        self._redis.delete(f"{SESSION_PREFIX}{session_id}")

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Returns True if the call is allowed, False if the limit was hit."""
        redis_key = f"{RATE_LIMIT_PREFIX}{key}"
        count = self._redis.incr(redis_key)
        if count == 1:
            self._redis.expire(redis_key, window_seconds)
        return count <= limit
