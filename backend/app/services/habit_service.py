import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.memory import MemorySettings
from app.core import habits
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory
from app.repositories.collection_repository import CollectionRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.run_repository import RunRepository

_settings = MemorySettings()


@dataclass(frozen=True)
class Habit:
    collection_id: uuid.UUID
    # 0 to 1: how much the collection weighs in the routing.
    weight: float


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _score(item: UserMemory, now: datetime) -> float:
    """What the item is worth now: its score when it was written, faded since."""
    data = item.data or {}
    try:
        at = datetime.fromisoformat(data["at"])
        return habits.faded(float(data["score"]), at, now, _settings.MEMORY_LEARNING_HALF_LIFE_DAYS)
    except (KeyError, TypeError, ValueError):
        return 0.0


def is_visible(item: UserMemory, now: datetime) -> bool:
    """A sentence is always shown. A habit is shown - and used - once it is more than one use."""
    return not item.data or _score(item, now) >= habits.THRESHOLD


def _collection_of(item: UserMemory) -> uuid.UUID | None:
    return _uuid((item.data or {}).get("collection_id"))


class HabitService:
    """The collections a person uses most (#286), learned from their answers and used as a slight prior in the routing
    and to propose them first in the picker. Never a filter: a collection that is not a habit is searched all the same,
    and a habit that the person cannot read - deleted, access removed - is forgotten the next time it is looked at,
    never proposed. Counted without a model; it never writes over what the person wrote, nor when their memory is not
    in use."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.memories = MemoryRepository(db)
        self.collections = CollectionRepository(db)

    async def record_run(self, run_id: uuid.UUID) -> None:
        """Counts what an answer used. Best effort: it is made after the answer is kept and never makes it fail."""
        try:
            await self._record_run(run_id)
        except Exception:
            await self.db.rollback()
            logger.exception("Counting the collections an answer used failed")

    async def _record_run(self, run_id: uuid.UUID) -> None:
        if not (_settings.MEMORY_ENABLED and _settings.MEMORY_LEARNING_ENABLED):
            return
        run = await RunRepository(self.db).get_by_id(run_id)
        if run is None or run.memory_mode != "on" or run.guardrail_outcome == "blocked":
            return
        user_id = run.user_id
        if not await self.memories.enabled(user_id):
            return
        forgotten_until = await self.memories.learning_from(user_id)
        if forgotten_until is not None and run.created_at < forgotten_until:
            return

        citations = run.citations or []
        cited = {c for c in (_uuid(x.get("vdb_id")) for x in citations if x.get("cited")) if c}
        # What the person attached counts only for an answer that rests on something: a question with nothing found, or
        # a request about their memory, says nothing of what they use.
        pinned = {c for c in (_uuid(x) for x in run.pinned_collection_ids or []) if c} if citations else set()
        # Only what they may read - and never the temporary collection of a conversation, which is not in this set.
        used = (cited | pinned) & await self.collections.accessible_ids(user_id, run.user_groups or [])
        if not used:
            return

        now = datetime.now(UTC)
        names = await self.collections.names_by_id(list(used))
        existing = {cid: item for item in await self.memories.habit_items(user_id) if (cid := _collection_of(item))}
        for collection_id in used:
            weight = (habits.CITED if collection_id in cited else 0.0) + (
                habits.PINNED if collection_id in pinned else 0.0
            )
            item = existing.get(collection_id)
            if item is not None and item.origin == MemoryOrigin.EXPLICIT:
                continue
            score = (_score(item, now) if item is not None else 0.0) + weight
            data = {"collection_id": str(collection_id), "score": score, "at": now.isoformat()}
            expires_at = now + timedelta(days=_settings.MEMORY_HABITS_TTL_DAYS)
            value = habits.sentence(names.get(collection_id, ""))
            if item is not None:
                item.data, item.value, item.expires_at = data, value, expires_at
                item.confidence, item.evidence_count = habits.weight_of(score), item.evidence_count + 1
            elif await self.memories.count(user_id) < _settings.MEMORY_MAX_ITEMS:
                existing[collection_id] = await self.memories.add(
                    UserMemory(
                        user_id=user_id,
                        kind=MemoryKind.HABIT,
                        key=habits.key_of(collection_id),
                        value=value,
                        origin=MemoryOrigin.INFERRED,
                        confidence=habits.weight_of(score),
                        evidence_count=1,
                        expires_at=expires_at,
                        data=data,
                    )
                )
        await self._keep_the_best(list(existing.values()), now)
        await self.db.commit()

    async def _keep_the_best(self, items: list[UserMemory], now: datetime) -> None:
        """What has faded away is forgotten, and no more than `MEMORY_HABITS_MAX` are kept: the heaviest."""
        learned = (item for item in items if item.origin == MemoryOrigin.INFERRED)
        ranked = sorted(learned, key=lambda item: _score(item, now), reverse=True)
        for rank, item in enumerate(ranked):
            if rank >= _settings.MEMORY_HABITS_MAX or _score(item, now) < habits.FORGET_BELOW:
                await self.memories.delete(item)

    async def tidy(self, user_id: str, groups: Sequence[str]) -> None:
        """What the person can no longer read is forgotten; what remains is named as the collection is today."""
        items = await self.memories.habit_items(user_id)
        if not items:
            return
        accessible = await self.collections.accessible_ids(user_id, groups)
        names = await self.collections.names_by_id(list(accessible & {c for i in items if (c := _collection_of(i))}))
        changed = False
        for item in items:
            collection_id = _collection_of(item)
            if collection_id is None or collection_id not in accessible:
                await self.memories.delete(item)
                changed = True
            elif (
                item.origin == MemoryOrigin.INFERRED and (value := habits.sentence(names[collection_id])) != item.value
            ):
                item.value = value
                changed = True
        if changed:
            await self.db.commit()

    async def habits(self, user_id: str, groups: Sequence[str]) -> list[Habit]:
        """The collections to weigh in the routing, the heaviest first: the ones that are habits, that the person keeps
        on, and that they can read - the others are forgotten here."""
        if not (_settings.MEMORY_ENABLED and await self.memories.enabled(user_id)):
            return []
        await self.tidy(user_id, groups)
        now = datetime.now(UTC)
        found = [
            Habit(collection_id, habits.weight_of(_score(item, now)))
            for item in await self.memories.habit_items(user_id)
            if item.enabled
            and (item.expires_at is None or item.expires_at > now)
            and is_visible(item, now)
            and (collection_id := _collection_of(item))
        ]
        return sorted(found, key=lambda habit: habit.weight, reverse=True)
