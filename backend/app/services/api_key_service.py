import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ApiKeySettings
from app.core.api_keys import candidate_hashes, generate_key, hash_key, is_well_formed, visible_prefix
from app.core.security.factory import RequestContext
from app.core.security.keycloak_client import session_store
from app.models.api_key import ApiKey
from app.repositories.api_key_repository import ApiKeyRepository
from app.repositories.group_repository import GroupRepository
from app.schemas.api_key import ApiKeyCreate

_settings = ApiKeySettings()

# A key in use notes it at most this often.
_TOUCH_EVERY_SECONDS = 60


class ApiKeysDisabledError(Exception):
    """No pepper is set: keys are off."""


class InvalidApiKeyRequestError(Exception):
    """What was asked for a new key cannot be."""


class TooManyApiKeysError(Exception):
    pass


class ApiKeyNotFoundError(Exception):
    pass


class InvalidApiKeyError(Exception):
    """The key presented is not one that may be used (unknown, revoked, expired, or not for this)."""


class ApiKeyRateLimitedError(Exception):
    pass


class ApiKeyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.keys = ApiKeyRepository(db)

    async def create(self, user: RequestContext, body: ApiKeyCreate) -> tuple[ApiKey, str]:
        peppers = _settings.peppers
        if not peppers:
            raise ApiKeysDisabledError
        unknown = body.unknown_scopes()
        if unknown:
            raise InvalidApiKeyRequestError(f"Unknown scope: {', '.join(unknown)}")
        days = body.expires_in_days or _settings.API_KEY_DEFAULT_DAYS
        if days > _settings.API_KEY_MAX_DAYS:
            raise InvalidApiKeyRequestError(f"A key may last {_settings.API_KEY_MAX_DAYS} days at most")
        now = datetime.now(UTC)
        if await self.keys.count_usable(user.user_id, now) >= _settings.API_KEYS_PER_USER:
            raise TooManyApiKeysError

        key = generate_key()
        version, pepper = peppers[0]
        row = await self.keys.create(
            user_id=user.user_id,
            name=body.name.strip(),
            key_prefix=visible_prefix(key),
            key_hash=hash_key(key, version, pepper),
            scopes=list(dict.fromkeys(body.scopes)),
            expires_at=now + timedelta(days=days),
            owner_email=user.email or None,
            owner_groups=list(user.groups),
        )
        await self.db.commit()
        # Never the key itself: who made which key, and when.
        logger.info(f"API key {row.id} ({row.key_prefix}) created by {user.user_id}, scopes {row.scopes}")
        return row, key

    async def list_keys(self, user: RequestContext) -> list[ApiKey]:
        return list(await self.keys.list_by_owner(user.user_id))

    async def revoke(self, user: RequestContext, key_id: uuid.UUID) -> None:
        row = await self.keys.get_owned(key_id, user.user_id)
        if row is None:
            raise ApiKeyNotFoundError
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self.db.commit()
            logger.info(f"API key {row.id} ({row.key_prefix}) revoked by {user.user_id}")

    async def authenticate(self, token: str, scope: str) -> RequestContext:
        """Who a key stands for, when the key may be used for `scope`. Never a key's own reason for being refused is
        told to the caller: an unknown, a revoked and an expired key are all just not valid."""
        peppers = _settings.peppers
        if not peppers or not is_well_formed(token):
            raise InvalidApiKeyError
        row = await self.keys.get_by_hashes(candidate_hashes(token, peppers))
        now = datetime.now(UTC)
        if row is None or not row.is_usable(now) or scope not in row.scopes:
            raise InvalidApiKeyError
        if not session_store.check_rate_limit(f"api-key:{row.id}", _settings.API_KEY_RATE_LIMIT_PER_MINUTE, 60):
            raise ApiKeyRateLimitedError
        await self.keys.touch(row.id, now, _TOUCH_EVERY_SECONDS)
        await self.db.commit()
        # Their groups in Muffin are looked up now, as for a session; those of Keycloak are what they were when the
        # owner last logged in, a key having no token to read them from. Never an administrator.
        groups = list(dict.fromkeys([*row.owner_groups, *await GroupRepository(self.db).group_ids_of(row.user_id)]))
        return RequestContext(
            user_id=row.user_id, email=row.owner_email or "", roles=["user"], is_admin=False, groups=groups
        )

    async def refresh_owner(self, user_id: str, email: str | None, groups: list[str]) -> None:
        await self.keys.refresh_owner(user_id, email, groups)
        await self.db.commit()
