import base64
import binascii
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.notification import RETENTION_DAYS, Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationOut, NotificationPage, PreferenceOut

# What a person keeps at most: older ones go first.
KEEP_PER_USER = 500
# A person seen less than this long ago is not "seen" again: the look at the unread count is made every hour.
SEEN_EVERY = timedelta(minutes=5)

ROUTINE_COMPLETED = "routine.completed"
ROUTINE_FAILED = "routine.failed"
ROUTINE_SUSPENDED = "routine.suspended"
DOCUMENT_FAILED = "document.failed"
IMPORT_COMPLETED = "import.completed"
SHARE_RECEIVED = "share.received"
FEEDBACK_STATUS = "feedback.status"

# The types of notification, with what the preferences say of each. A type that is not here is refused: the table of
# preferences must not fill with what a caller invents.
TYPES: dict[str, tuple[str, str]] = {
    ROUTINE_COMPLETED: ("Routine terminée", "Le résultat d'une de vos routines est prêt."),
    ROUTINE_FAILED: ("Routine en échec", "Une de vos routines n'a pas pu s'exécuter."),
    ROUTINE_SUSPENDED: ("Routine suspendue", "Une de vos routines a été mise de côté (échecs répétés, inactivité…)."),
    DOCUMENT_FAILED: ("Document non traité", "Un document que vous avez ajouté n'a pas pu être traité."),
    IMPORT_COMPLETED: ("Import terminé", "Un import de documents (ZIP) est terminé."),
    SHARE_RECEIVED: ("Collection partagée", "Une collection est partagée avec un de vos groupes."),
    FEEDBACK_STATUS: ("Suite d'un signalement", "Le statut d'un signalement que vous avez fait a changé."),
}


class UnknownNotificationTypeError(Exception):
    pass


class NotificationNotFoundError(Exception):
    pass


class InvalidCursorError(Exception):
    pass


def _cursor_of(notification: Notification) -> str:
    raw = f"{notification.created_at.isoformat()}|{notification.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _read_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        moment, last_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(moment), uuid.UUID(last_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise InvalidCursorError from error


def _link(link: str | None) -> str | None:
    """A path of the application only: a notification never leads away from it."""
    if link and link.startswith("/") and not link.startswith("//") and "\\" not in link:
        return link[:300]
    return None


def _present(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        summary=notification.summary,
        link=notification.link,
        data=notification.data or {},
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.notifications = NotificationRepository(db)

    async def notify(
        self,
        user_id: str,
        type_: str,
        title: str,
        summary: str = "",
        link: str | None = None,
        data: dict | None = None,
    ) -> Notification | None:
        """Tells a person something, unless they turned that type off. Flushes only: the caller commits. What it takes
        is what the person may already read - never the text of an answer."""
        if type_ not in TYPES:
            raise UnknownNotificationTypeError(type_)
        if (await self.notifications.preferences(user_id)).get(type_, True) is False:
            return None
        notification = await self.notifications.add(
            Notification(
                user_id=user_id,
                type=type_,
                title=title.strip()[:200],
                summary=summary.strip()[:500],
                link=_link(link),
                data=data or {},
            )
        )
        await self.notifications.trim(user_id, KEEP_PER_USER)
        return notification

    async def page(
        self, user: RequestContext, limit: int = 20, cursor: str | None = None, unread_only: bool = False
    ) -> NotificationPage:
        before = _read_cursor(cursor) if cursor else None
        rows = list(await self.notifications.newest(user.user_id, limit + 1, before, unread_only))
        page = rows[:limit]
        return NotificationPage(
            items=[_present(row) for row in page],
            next_cursor=_cursor_of(page[-1]) if len(rows) > limit and page else None,
            unread=await self.notifications.unread_count(user.user_id),
        )

    async def unread_count(self, user: RequestContext) -> int:
        """The number the bell shows. Asked when the application opens and then every hour while it is open, so it is
        also what tells that the person is there (the routines of someone who left are not kept running)."""
        await self.notifications.touch_profile(user.user_id, datetime.now(UTC) - SEEN_EVERY)
        count = await self.notifications.unread_count(user.user_id)
        await self.db.commit()
        return count

    async def mark_read(self, user: RequestContext, ids: list[uuid.UUID] | None) -> int:
        changed = await self.notifications.mark_read(user.user_id, ids or None)
        await self.db.commit()
        return changed

    async def delete(self, user: RequestContext, notification_id: uuid.UUID) -> None:
        if not await self.notifications.delete(user.user_id, notification_id):
            raise NotificationNotFoundError(str(notification_id))
        await self.db.commit()

    async def preferences(self, user: RequestContext) -> list[PreferenceOut]:
        chosen = await self.notifications.preferences(user.user_id)
        return [
            PreferenceOut(type=type_, label=label, description=description, app=chosen.get(type_, True))
            for type_, (label, description) in TYPES.items()
        ]

    async def set_preferences(self, user: RequestContext, changes: dict[str, bool]) -> list[PreferenceOut]:
        unknown = [type_ for type_ in changes if type_ not in TYPES]
        if unknown:
            raise UnknownNotificationTypeError(", ".join(unknown))
        for type_, enabled in changes.items():
            await self.notifications.set_preference(user.user_id, type_, enabled)
        await self.db.commit()
        return await self.preferences(user)

    async def purge(self) -> int:
        """Forgets what is older than the retention. Called by the sweep of the routines, which runs everywhere."""
        removed = await self.notifications.delete_older_than(datetime.now(UTC) - timedelta(days=RETENTION_DAYS))
        await self.db.commit()
        return removed


async def notify(
    user_id: str | None,
    type_: str,
    title: str,
    summary: str = "",
    link: str | None = None,
    data: dict | None = None,
) -> None:
    """Tells a person something from anywhere in the application, **in a session and a transaction of its own** and
    never failing: what raised the event must not fail because the bell could not be rung."""
    if not user_id:
        return
    try:
        async with async_session_factory() as session:
            created = await NotificationService(session).notify(user_id, type_, title, summary, link, data)
            if created is not None:
                await session.commit()
    except Exception:
        logger.exception(f"The notification {type_} could not be recorded")
