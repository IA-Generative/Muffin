from app.core.security.factory import RequestContext
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository
from app.services.copied_collections import ensure_not_copied

from .collection_service import CollectionNotEditableError, CollectionNotFoundError


async def require_editable_collection(
    collections: CollectionRepository, user: RequestContext, collection_id
) -> Collection:
    """Who may change a living document (#171): the collection's owner, anyone a share lets write on it or on
    one of its ancestors (#454), or a platform administrator - but an administrator only on a collection they
    can already see (their own, public, or shared with them), never on someone else's private one, whose
    existence isn't theirs to learn.

    A collection the caller can't see at all is "not found"; one they can see but may not edit is
    "not editable", so the UI can say so instead of pretending it doesn't exist."""
    collection = await collections.get_accessible(collection_id, user.user_id, user.groups)
    if collection is None:
        raise CollectionNotFoundError(str(collection_id))
    # A copy of another system's collection is changed there (#464): not even by an administrator.
    ensure_not_copied(collection)
    editable = await collections.filter_editable_ids([collection], user.user_id, user.groups, user.is_admin)
    if collection.id not in editable:
        raise CollectionNotEditableError(str(collection_id))
    return collection
