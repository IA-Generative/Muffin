from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.memory import MemorySettings
from app.core import style_signals
from app.models.feedback import Feedback, FeedbackReason
from app.models.message import Message
from app.models.run import Run
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory
from app.repositories.memory_repository import MemoryRepository

_settings = MemorySettings()

# How far back, and how many, of a person's feedbacks are looked at: what is older has faded anyway.
_WINDOW_DAYS = 90
_MAX_FEEDBACKS = 200


class MemoryLearningService:
    """What the 👍/👎 of a person teach the assistant about the style they like (#285). Not a model: rules on what they
    said and what they rated (`app/core/style_signals.py`), added up with a fade over time.

    What is learned is **recomputed** from their recent feedbacks each time one is given, rather than adjusted a step
    at a time: a feedback that is changed or gone is simply no longer in the sum, a signal that agreed with nothing
    fades out, and the same feedbacks always give the same preferences. It is done in the request of the feedback, so
    that the next answer already has it. It never writes over what the person wrote, and never when their memory is
    off - nor from a conversation where it was not in use (without memory, with an assistant)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.memories = MemoryRepository(db)

    async def learn(self, user_id: str) -> None:
        """Never lets a failure reach the person who only gave a 👍: the feedback is kept, what it would have taught is
        learned from the next one."""
        try:
            await self._learn(user_id)
        except Exception:
            await self.db.rollback()
            logger.exception("Learning from the feedback of a person failed")

    async def _learn(self, user_id: str) -> None:
        if not (_settings.MEMORY_ENABLED and _settings.MEMORY_LEARNING_ENABLED):
            return
        if not await self.memories.enabled(user_id):
            return
        now = datetime.now(UTC)
        scores = await self._scores(user_id, now)
        for dimension in sorted({dimension for dimension, _ in style_signals.LEARNED}):
            total, evidence = scores.get(dimension, (0.0, 0))
            await self._settle(user_id, dimension, total, evidence, now)
        await self.db.commit()

    async def _scores(self, user_id: str, now: datetime) -> dict[str, tuple[float, int]]:
        since = now - timedelta(days=_WINDOW_DAYS)
        forgotten_until = await self.memories.learning_from(user_id)
        if forgotten_until is not None:
            since = max(since, forgotten_until)
        rows = (
            await self.db.execute(
                select(Feedback, Message.content, Run.memory_mode)
                .join(Message, Message.id == Feedback.message_id)
                .outerjoin(Run, Run.id == Message.run_id)
                .where(Feedback.user_id == user_id, Feedback.created_at >= since)
                .order_by(Feedback.created_at.desc())
                .limit(_MAX_FEEDBACKS)
            )
        ).all()
        reasons: dict = {}
        if rows:
            for feedback_id, reason in await self.db.execute(
                select(FeedbackReason.feedback_id, FeedbackReason.reason).where(
                    FeedbackReason.feedback_id.in_([feedback.id for feedback, *_ in rows])
                )
            ):
                reasons.setdefault(feedback_id, []).append(reason.value)

        scores: dict[str, tuple[float, int]] = {}
        seen: set = set()
        for feedback, answer, memory_mode in rows:
            # The latest feedback of a message is the one that counts: changing one's mind replaces, it does not add.
            if feedback.message_id in seen:
                continue
            seen.add(feedback.message_id)
            if memory_mode != "on":
                continue
            age = style_signals.age_in_days(feedback.created_at, now)
            touched: set[str] = set()
            for signal in style_signals.signals_of(
                feedback.value.value, reasons.get(feedback.id, []), feedback.comment, answer
            ):
                total, evidence = scores.get(signal.dimension, (0.0, 0))
                weight = style_signals.decayed(signal.weight, age, _settings.MEMORY_LEARNING_HALF_LIFE_DAYS)
                scores[signal.dimension] = (total + signal.direction * weight, evidence)
                touched.add(signal.dimension)
            for dimension in touched:
                total, evidence = scores[dimension]
                scores[dimension] = (total, evidence + 1)
        return scores

    async def _settle(self, user_id: str, dimension: str, total: float, evidence: int, now: datetime) -> None:
        key = style_signals.LEARNED[(dimension, 1)][0]
        item = await self.memories.by_key(user_id, MemoryKind.PREFERENCE, key)
        if item is not None and item.origin == MemoryOrigin.EXPLICIT:
            return
        if abs(total) < style_signals.THRESHOLD:
            # Not enough, or it faded, or it was contradicted: what was learned is no longer.
            if item is not None:
                await self.memories.delete(item)
            return
        _, value = style_signals.LEARNED[(dimension, 1 if total > 0 else -1)]
        confidence = min(1.0, abs(total) / 3)
        expires_at = now + timedelta(days=_settings.MEMORY_LEARNED_TTL_DAYS)
        if item is not None:
            item.value, item.confidence, item.evidence_count, item.expires_at = value, confidence, evidence, expires_at
            return
        if await self.memories.count(user_id) >= _settings.MEMORY_MAX_ITEMS:
            return
        await self.memories.add(
            UserMemory(
                user_id=user_id,
                kind=MemoryKind.PREFERENCE,
                key=key,
                value=value,
                origin=MemoryOrigin.INFERRED,
                confidence=confidence,
                evidence_count=evidence,
                expires_at=expires_at,
            )
        )
