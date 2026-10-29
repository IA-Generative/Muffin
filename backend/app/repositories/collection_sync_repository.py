from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.sharing import mask_email, mask_group
from app.models.collection import Collection, CollectionShare, CollectionVisibility, ShareStatus, ShareSubjectType
from app.models.group import Group, ResourceSource
from app.repositories.collection_repository import CollectionRepository
from app.schemas.collection_sync import CollectionSyncIn


@dataclass(frozen=True)
class CollectionSyncResult:
    collection: Collection
    created: bool
    shares_added: int
    shares_removed: int
    unknown_groups: list[str]


class CollectionSyncRepository:
    """The collections copied from another system (#453): made to be what that system has, never edited here."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, source: ResourceSource, external_id: str) -> Collection | None:
        return await self.db.scalar(
            select(Collection)
            .where(Collection.source == source, Collection.external_id == external_id)
            .options(selectinload(Collection.settings))
        )

    async def sync(self, source: ResourceSource, external_id: str, data: CollectionSyncIn) -> CollectionSyncResult:
        collection = await self._get(source, external_id)
        created = collection is None
        if collection is None:
            collection = await CollectionRepository(self.db).create(
                owner_id=data.owner_id,
                name=data.name,
                description=data.description,
                embedding_model=data.embedding_model,
            )
            collection.source, collection.external_id = source, external_id
        else:
            collection.owner_id, collection.name, collection.description = data.owner_id, data.name, data.description
            collection.settings.embedding_model = data.embedding_model
        collection.visibility = CollectionVisibility.PUBLIC if data.public else CollectionVisibility.PRIVATE

        wanted, unknown_groups = await self._wanted_shares(source, data)
        shares = list(
            await self.db.scalars(select(CollectionShare).where(CollectionShare.collection_id == collection.id))
        )
        current = {(share.subject_type, share.subject_id) for share in shares}
        stale = [share for share in shares if (share.subject_type, share.subject_id) not in wanted]
        if stale:
            await self.db.execute(delete(CollectionShare).where(CollectionShare.id.in_([share.id for share in stale])))
        added = [key for key in wanted if key not in current]
        self.db.add_all(
            CollectionShare(
                collection_id=collection.id,
                subject_type=subject_type,
                subject_id=subject_id,
                status=ShareStatus.ACTIVE,
                display_hint=wanted[(subject_type, subject_id)],
            )
            for subject_type, subject_id in added
        )
        await self.db.flush()
        return CollectionSyncResult(collection, created, len(added), len(stale), unknown_groups)

    async def _wanted_shares(
        self, source: ResourceSource, data: CollectionSyncIn
    ) -> tuple[dict[tuple[ShareSubjectType, str], str], list[str]]:
        """(subject type, subject id) -> the hint shown for it. A group is shared by the id Muffin gave its copy."""
        wanted: dict[tuple[ShareSubjectType, str], str] = {
            (ShareSubjectType.USER, user.subject_id): mask_email(user.email) if user.email else "***"
            for user in data.user_shares
        }
        groups = {
            group.external_id: group
            for group in await self.db.scalars(
                select(Group).where(Group.source == source, Group.external_id.in_(data.group_external_ids))
            )
        }
        for external_id in data.group_external_ids:
            if (group := groups.get(external_id)) is not None:
                wanted[(ShareSubjectType.GROUP, str(group.id))] = mask_group(group.name)
        return wanted, [external_id for external_id in data.group_external_ids if external_id not in groups]

    async def external_ids(self, source: ResourceSource) -> list[str]:
        result = await self.db.scalars(
            select(Collection.external_id).where(Collection.source == source, Collection.external_id.is_not(None))
        )
        return list(result)
