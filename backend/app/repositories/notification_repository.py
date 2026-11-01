import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import CHANNEL_APP, Notification, NotificationPreference
from app.models.token_usage import UserProfile


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, notification: Notification) -> Notification:
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def newest(
        self, user_id: str, limit: int, before: tuple[datetime, uuid.UUID] | None, unread_only: bool
    ) -> Sequence[Notification]:
        """Newest first, by keyset: what is older than the (date, id) given."""
        statement = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        if before is not None:
            moment, last_id = before
            statement = statement.where(
                or_(
                    Notification.created_at < moment,
                    and_(Notification.created_at == moment, Notification.id < last_id),
                )
            )
        result = await self.db.execute(
            statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        )
        return result.scalars().all()

    async def unread_count(self, user_id: str) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
            or 0
        )

    async def mark_read(self, user_id: str, ids: Sequence[uuid.UUID] | None) -> int:
        statement = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        if ids is not None:
            statement = statement.where(Notification.id.in_(ids))
        return (await self.db.execute(statement.values(read_at=func.now()))).rowcount

    async def delete(self, user_id: str, notification_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            delete(Notification).where(Notification.user_id == user_id, Notification.id == notification_id)
        )
        return result.rowcount > 0

    async def delete_older_than(self, moment: datetime) -> int:
        return (await self.db.execute(delete(Notification).where(Notification.created_at < moment))).rowcount

    async def trim(self, user_id: str, keep: int) -> int:
        """Keeps the `keep` newest notifications of a person: a routine every hour must not fill the table."""
        oldest_kept = (
            select(Notification.created_at)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(keep - 1)
            .limit(1)
            .scalar_subquery()
        )
        result = await self.db.execute(
            delete(Notification).where(Notification.user_id == user_id, Notification.created_at < oldest_kept)
        )
        return result.rowcount

    async def preferences(self, user_id: str) -> dict[str, bool]:
        result = await self.db.execute(
            select(NotificationPreference.type, NotificationPreference.enabled).where(
                NotificationPreference.user_id == user_id, NotificationPreference.channel == CHANNEL_APP
            )
        )
        return {row.type: row.enabled for row in result}

    async def set_preference(self, user_id: str, type_: str, enabled: bool) -> None:
        statement = insert(NotificationPreference).values(
            user_id=user_id, type=type_, channel=CHANNEL_APP, enabled=enabled
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    NotificationPreference.user_id,
                    NotificationPreference.type,
                    NotificationPreference.channel,
                ],
                set_={"enabled": statement.excluded.enabled, "updated_at": func.now()},
            )
        )

    async def touch_profile(self, user_id: str, older_than: datetime) -> None:
        """The person was seen: the date their routines read, moved only when it is older than `older_than`, so that
        the minute-by-minute look at the unread count does not write every time."""
        await self.db.execute(
            update(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                or_(UserProfile.last_seen_at.is_(None), UserProfile.last_seen_at < older_than),
            )
            .values(last_seen_at=func.now())
        )
