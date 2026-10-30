from app.models.collection import Collection


class CopiedCollectionError(Exception):
    """The collection is a copy of another system's (#462, #464): what is in it, and how it is shared and set up, is
    that system's. It is read, searched and talked to here, and changed there - until Muffin takes it over."""


def ensure_not_copied(collection: Collection) -> Collection:
    if collection.is_copied:
        raise CopiedCollectionError(str(collection.id))
    return collection
