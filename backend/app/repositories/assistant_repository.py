import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import Assistant, AssistantShare
from app.models.collection import CollectionVisibility, SharePermission, ShareStatus, ShareSubjectType


def _active_share(user_id: str, group_ids: Sequence[str], *, write: bool = False):
    """An ACTIVE share of the assistant, direct or to one of the caller's groups (letting write when `write`)."""
    conditions = [
        AssistantShare.assistant_id == Assistant.id,
        AssistantShare.status == ShareStatus.ACTIVE,
    ]
    if write:
        conditions.append(AssistantShare.permission == SharePermission.WRITE)
    direct = exists().where(
        *conditions, AssistantShare.subject_type == ShareSubjectType.USER, AssistantShare.subject_id == user_id
    )
    if not group_ids:
        return direct
    group = exists().where(
        *conditions, AssistantShare.subject_type == ShareSubjectType.GROUP, AssistantShare.subject_id.in_(group_ids)
    )
    return or_(direct, group)


class AssistantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _readable_where(user_id: str, group_ids: Sequence[str]):
        """Who sees an assistant: its author, everyone for a public one, those it is shared with."""
        return or_(
            Assistant.owner_id == user_id,
            Assistant.visibility == CollectionVisibility.PUBLIC,
            _active_share(user_id, group_ids),
        )

    @staticmethod
    def _writable_where(user_id: str, group_ids: Sequence[str]):
        return or_(Assistant.owner_id == user_id, _active_share(user_id, group_ids, write=True))

    async def get_accessible(
        self, assistant_id: uuid.UUID, user_id: str, group_ids: Sequence[str]
    ) -> tuple[Assistant, bool] | None:
        """The assistant if the caller may read it, with whether they may also change it."""
        row = (
            await self.db.execute(
                select(Assistant, self._writable_where(user_id, group_ids).label("writable")).where(
                    Assistant.id == assistant_id, self._readable_where(user_id, group_ids)
                )
            )
        ).first()
        return (row[0], bool(row[1])) if row else None

    async def list_accessible(self, user_id: str, group_ids: Sequence[str]) -> list[tuple[Assistant, bool]]:
        rows = await self.db.execute(
            select(Assistant, self._writable_where(user_id, group_ids).label("writable"))
            .where(self._readable_where(user_id, group_ids))
            .order_by(func.lower(Assistant.name), Assistant.created_at)
        )
        return [(row[0], bool(row[1])) for row in rows.all()]

    async def share_counts(self, assistant_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not assistant_ids:
            return {}
        rows = await self.db.execute(
            select(AssistantShare.assistant_id, func.count())
            .where(AssistantShare.assistant_id.in_(assistant_ids))
            .group_by(AssistantShare.assistant_id)
        )
        return {assistant_id: count for assistant_id, count in rows.all()}

    async def create(self, owner_id: str, **fields) -> Assistant:  # noqa: ANN003
        assistant = Assistant(owner_id=owner_id, **fields)
        self.db.add(assistant)
        await self.db.flush()
        return assistant

    async def delete(self, assistant: Assistant) -> None:
        await self.db.delete(assistant)

    # --- shares ---

    async def create_share(
        self,
        assistant_id: uuid.UUID,
        subject_type: ShareSubjectType,
        identifier_hash: str,
        display_hint: str,
        permission: SharePermission,
    ) -> AssistantShare:
        share = AssistantShare(
            assistant_id=assistant_id,
            subject_type=subject_type,
            permission=permission,
            status=ShareStatus.PENDING,
            invited_identifier_hash=identifier_hash,
            display_hint=display_hint,
        )
        self.db.add(share)
        await self.db.flush()
        return share

    async def create_active_group_share(
        self, assistant_id: uuid.UUID, group_id: uuid.UUID, group_name: str, permission: SharePermission
    ) -> AssistantShare:
        share = AssistantShare(
            assistant_id=assistant_id,
            subject_type=ShareSubjectType.GROUP,
            status=ShareStatus.ACTIVE,
            permission=permission,
            subject_id=str(group_id),
            display_hint=group_name,
        )
        self.db.add(share)
        await self.db.flush()
        return share

    async def list_shares(self, assistant_id: uuid.UUID) -> Sequence[AssistantShare]:
        result = await self.db.execute(
            select(AssistantShare)
            .where(AssistantShare.assistant_id == assistant_id)
            .order_by(AssistantShare.created_at.desc())
        )
        return result.scalars().all()

    async def get_share(self, assistant_id: uuid.UUID, share_id: uuid.UUID) -> AssistantShare | None:
        result = await self.db.execute(
            select(AssistantShare).where(AssistantShare.id == share_id, AssistantShare.assistant_id == assistant_id)
        )
        return result.scalar_one_or_none()

    async def delete_share(self, share: AssistantShare) -> None:
        await self.db.delete(share)

    async def resolve_pending_user_shares(self, email_hash: str, user_id: str) -> None:
        """Same passive resolution as the collections' (CollectionRepository.resolve_pending_user_shares)."""
        await self.db.execute(
            update(AssistantShare)
            .where(
                AssistantShare.subject_type == ShareSubjectType.USER,
                AssistantShare.status == ShareStatus.PENDING,
                AssistantShare.invited_identifier_hash == email_hash,
            )
            .values(status=ShareStatus.ACTIVE, subject_id=user_id, invited_identifier_hash=None)
        )

    async def resolve_pending_group_shares(self, group_hash: str, group_id: str) -> None:
        await self.db.execute(
            update(AssistantShare)
            .where(
                AssistantShare.subject_type == ShareSubjectType.GROUP,
                AssistantShare.status == ShareStatus.PENDING,
                AssistantShare.invited_identifier_hash == group_hash,
            )
            .values(status=ShareStatus.ACTIVE, subject_id=group_id, invited_identifier_hash=None)
        )
