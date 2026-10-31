import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_store import SecretProvider, SecretStoreError, get_provider
from app.db import async_session_factory
from app.models.stored_secret import StoredSecret

# What a purpose may look like: it is chosen by the code that stores a secret, never by a user, and it is part of what
# the ciphertext is bound to.
_PURPOSE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,99}$")
# A secret this long shows its last characters to tell it from another; a shorter one shows nothing of itself.
_HINT_MIN_LENGTH = 16
_HINT_LENGTH = 4
# An access is noted at most this often per secret.
_TOUCH_EVERY = timedelta(minutes=1)


class SecretNotFoundError(Exception):
    pass


class InvalidPurposeError(ValueError):
    pass


@dataclass(frozen=True)
class RewrapProgress:
    rewrapped: int
    remaining: int
    current_version: str


def _context(secret_id: uuid.UUID, owner: str | None, purpose: str) -> str:
    """What a ciphertext is bound to: it opens for this row, this owner and this purpose, and for nothing else."""
    return f"{secret_id}|{owner or '-'}|{purpose}"


def _hint(plaintext: str) -> str:
    return plaintext[-_HINT_LENGTH:] if len(plaintext) >= _HINT_MIN_LENGTH else ""


class SecretStore:
    """The secrets Muffin must read back (#521). `put` encrypts and stores; `reveal` opens one, for the code that is
    about to use it and for nothing else - no route of the API returns a secret, and an owner or a purpose that is not
    the row's is as good as a row that does not exist.

    The caller commits, like for any repository."""

    def __init__(self, db: AsyncSession, provider: SecretProvider | None = None) -> None:
        self.db = db
        self._provider = provider

    @property
    def provider(self) -> SecretProvider:
        return self._provider or get_provider()

    async def put(self, *, owner: str | None, purpose: str, plaintext: str, created_by: str) -> StoredSecret:
        if not _PURPOSE.match(purpose):
            raise InvalidPurposeError(purpose)
        secret_id = uuid.uuid4()
        ciphertext = await self.provider.encrypt(plaintext, context=_context(secret_id, owner, purpose))
        row = StoredSecret(
            id=secret_id,
            owner_id=owner,
            purpose=purpose,
            ciphertext=ciphertext,
            key_version=self.provider.version_of(ciphertext),
            hint=_hint(plaintext),
            created_by=created_by,
        )
        self.db.add(row)
        await self.db.flush()
        # Who and what, never the secret.
        logger.info(f"Secret {row.id} ({purpose}) stored for {owner or 'the deployment'} by {created_by}")
        return row

    async def get(self, secret_id: uuid.UUID, *, owner: str | None, purpose: str) -> StoredSecret:
        row = await self.db.get(StoredSecret, secret_id)
        if row is None or row.owner_id != owner or row.purpose != purpose:
            raise SecretNotFoundError
        return row

    async def reveal(self, secret_id: uuid.UUID, *, owner: str | None, purpose: str) -> str:
        row = await self.get(secret_id, owner=owner, purpose=purpose)
        plaintext = await self.provider.decrypt(row.ciphertext, context=_context(row.id, row.owner_id, row.purpose))
        await self._note_access(row.id)
        return plaintext

    async def replace(self, secret_id: uuid.UUID, plaintext: str, *, owner: str | None, purpose: str) -> StoredSecret:
        row = await self.get(secret_id, owner=owner, purpose=purpose)
        row.ciphertext = await self.provider.encrypt(plaintext, context=_context(row.id, row.owner_id, row.purpose))
        row.key_version = self.provider.version_of(row.ciphertext)
        row.hint = _hint(plaintext)
        row.rotated_at = datetime.now(UTC)
        await self.db.flush()
        logger.info(f"Secret {row.id} ({purpose}) replaced")
        return row

    async def delete(self, secret_id: uuid.UUID, *, owner: str | None, purpose: str) -> None:
        row = await self.get(secret_id, owner=owner, purpose=purpose)
        await self.db.delete(row)
        await self.db.flush()
        logger.info(f"Secret {secret_id} ({purpose}) deleted")

    async def rewrap_batch(self, limit: int = 200) -> RewrapProgress:
        """Brings the secrets made with an older version of the key to the latest one, `limit` at a time, without any of
        them being shown to this process (Vault) - what follows a rotation of the key."""
        current = await self.provider.current_version()
        rows = (
            (
                await self.db.execute(
                    select(StoredSecret)
                    .where(StoredSecret.key_version != current)
                    .order_by(StoredSecret.created_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.ciphertext = await self.provider.rewrap(
                row.ciphertext, context=_context(row.id, row.owner_id, row.purpose)
            )
            row.key_version = self.provider.version_of(row.ciphertext)
            row.rotated_at = datetime.now(UTC)
        await self.db.flush()
        remaining = await self.db.scalar(
            select(func.count()).select_from(StoredSecret).where(StoredSecret.key_version != current)
        )
        return RewrapProgress(rewrapped=len(rows), remaining=remaining or 0, current_version=current)

    async def versions(self) -> dict[str, int]:
        """How many secrets there are per version of the key: what shows a rotation's progress."""
        result = await self.db.execute(
            select(StoredSecret.key_version, func.count()).group_by(StoredSecret.key_version)
        )
        return {version: count for version, count in result.all()}

    @staticmethod
    async def _note_access(secret_id: uuid.UUID) -> None:
        """When a secret was last used, at most once a minute - in a session of its own: the caller's transaction is not
        this one's to commit. Best effort."""
        now = datetime.now(UTC)
        try:
            async with async_session_factory() as db:
                await db.execute(
                    update(StoredSecret)
                    .where(
                        StoredSecret.id == secret_id,
                        (StoredSecret.last_accessed_at.is_(None))
                        | (StoredSecret.last_accessed_at < now - _TOUCH_EVERY),
                    )
                    .values(last_accessed_at=now)
                )
                await db.commit()
        except Exception:
            logger.warning(f"Could not note the use of secret {secret_id}", exc_info=True)


__all__ = ["InvalidPurposeError", "RewrapProgress", "SecretNotFoundError", "SecretStore", "SecretStoreError"]
