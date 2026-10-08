from app.core.security.factory import RequestContext
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository

from .collection_service import CollectionNotEditableError, CollectionNotFoundError


async def require_editable_collection(
    collections: CollectionRepository, user: RequestContext, collection_id
) -> Collection:
    """Who may change a living document (#171): the collection's owner, or a platform administrator
    - but an administrator only on a collection they can already see (their own, public, or shared
    with them), never on someone else's private one, whose existence isn't theirs to learn.

    A collection the caller can't see at all is "not found"; one they can see but may not edit is
    "not editable", so the UI can say so instead of pretending it doesn't exist."""
    collection = await collections.get_accessible(collection_id, user.user_id, user.groups)
    if collection is None:
        raise CollectionNotFoundError(str(collection_id))
    if collection.owner_id != user.user_id and not user.is_admin:
        raise CollectionNotEditableError(str(collection_id))
    return collection


def can_edit(user: RequestContext, collection: Collection) -> bool:
    """The same rule for a collection already loaded as visible to `user` (see above)."""
    return collection.owner_id == user.user_id or user.is_admin
