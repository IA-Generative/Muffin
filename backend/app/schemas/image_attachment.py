import uuid

from pydantic import BaseModel


class AttachmentStatusOut(BaseModel):
    """What the chat needs to offer the attachment of images (#512): only when a model of the hub can read them."""

    available: bool
    # The model that will read them when the one that writes the answer cannot: the first of the hub's that can.
    model: str | None = None
    max_images: int
    max_bytes: int
    types: list[str]


class AttachmentOut(BaseModel):
    """An image chosen in the composer, kept until the message that carries it is sent."""

    id: uuid.UUID
    content_type: str
    width: int
    height: int
    size_bytes: int
