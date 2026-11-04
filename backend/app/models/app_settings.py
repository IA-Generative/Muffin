from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppSettings(Base):
    """Single global config row (id is always 1), admin-only.

    embedding_model is fixed across every collection rather than a per-
    collection choice: comparing a query's embedding against every
    collection's description embedding to pick the right one (see
    CollectionDescriptionEmbedding) only works if they all live in the same
    embedding space."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # The model that classifies a request in auto mode (its level, complexity and intent). None: the model with the
    # lowest score among those the automatic choice may pick - the cheapest, since it is called on every request.
    classifier_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
