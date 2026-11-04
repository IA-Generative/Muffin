from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEFAULT_MODEL_SCORE = 50


class ModelProfile(Base):
    """What an administrator thinks a model of the hub is able to do, for the automatic choice of the model (#auto).

    One row per model the administrator has described: a model without a row is still usable by hand, and in auto mode
    it is taken with the default score. What the model *can* do (chat, vision, embeddings, image, speech...) is not
    here: the backend works it out from the hub and the other settings, and shows it as tags nobody edits."""

    __tablename__ = "model_profiles"

    model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    # How hard a task this model handles well, from 0 (a trivial question) to 100 (the hardest tasks).
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_MODEL_SCORE, server_default="50")
    # In the administrator's words, what it does correctly: read by the classifier to tell the models apart.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether the automatic choice may pick it. Off: still available by hand.
    auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
