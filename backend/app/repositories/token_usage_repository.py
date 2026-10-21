import uuid
from datetime import datetime

from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.document import Document
from app.models.run import Run
from app.models.token_usage import TokenUsage, UserProfile


def _sums():
    return (
        func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
        func.count(TokenUsage.id).label("calls"),
    )


def _biggest_first():
    return func.sum(TokenUsage.total_tokens).desc()


class TokenUsageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, usage: TokenUsage) -> None:
        self.db.add(usage)

    async def run_user(self, run_id: uuid.UUID) -> str | None:
        return await self.db.scalar(select(Run.user_id).where(Run.id == run_id))

    async def document_user(self, document_id: uuid.UUID) -> str | None:
        """Whoever added the document, or its collection's owner for one added before that was
        tracked (or by the pipeline itself, e.g. a ZIP import)."""
        row = (
            await self.db.execute(
                select(Document.added_by_user_id, Collection.owner_id)
                .join(Collection, Collection.id == Document.collection_id)
                .where(Document.id == document_id)
            )
        ).first()
        return (row.added_by_user_id or row.owner_id) if row else None

    async def collection_user(self, collection_id: uuid.UUID) -> str | None:
        return await self.db.scalar(select(Collection.owner_id).where(Collection.id == collection_id))

    async def save_profile(self, user_id: str, display: str, email: str | None) -> None:
        statement = insert(UserProfile).values(user_id=user_id, display=display, email=email)
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[UserProfile.user_id],
                set_={
                    "display": statement.excluded.display,
                    "email": statement.excluded.email,
                    "updated_at": func.now(),
                },
            )
        )

    def _filtered(self, statement, since: datetime, user_id: str | None):
        statement = statement.where(TokenUsage.created_at >= since)
        return statement.where(TokenUsage.user_id == user_id) if user_id is not None else statement

    async def totals(self, since: datetime, user_id: str | None):
        return (await self.db.execute(self._filtered(select(*_sums()), since, user_id))).one()

    async def by_step(self, since: datetime, user_id: str | None):
        statement = select(TokenUsage.step, *_sums()).group_by(TokenUsage.step).order_by(_biggest_first())
        return (await self.db.execute(self._filtered(statement, since, user_id))).all()

    async def by_day(self, since: datetime, user_id: str | None):
        day = cast(TokenUsage.created_at, Date).label("day")
        statement = select(day, *_sums()).group_by(day).order_by(day)
        return (await self.db.execute(self._filtered(statement, since, user_id))).all()

    async def by_model(self, since: datetime, user_id: str | None):
        statement = select(TokenUsage.model, *_sums()).group_by(TokenUsage.model).order_by(_biggest_first())
        return (await self.db.execute(self._filtered(statement, since, user_id))).all()

    async def by_user(self, since: datetime):
        statement = (
            select(TokenUsage.user_id, UserProfile.display, UserProfile.email, *_sums())
            .outerjoin(UserProfile, UserProfile.user_id == TokenUsage.user_id)
            .where(TokenUsage.created_at >= since)
            .group_by(TokenUsage.user_id, UserProfile.display, UserProfile.email)
            .order_by(_biggest_first())
        )
        return (await self.db.execute(statement)).all()
