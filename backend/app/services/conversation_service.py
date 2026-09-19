import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import SCORE_DISCUSSION_TASK, enqueue_score_discussion
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.discussion_feedback_repository import DiscussionFeedbackRepository
from app.repositories.discussion_score_repository import DiscussionScoreRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.conversation import ConversationOut, MessageOut
from app.schemas.discussion_feedback import DiscussionFeedbackOut
from app.schemas.discussion_score import DiscussionScoreOut
from app.schemas.pagination import Page, PaginationParams


class ConversationNotFoundError(Exception):
    pass


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)
        self.discussion_scores = DiscussionScoreRepository(db)
        self.discussion_feedbacks = DiscussionFeedbackRepository(db)
        self.tasks = TaskRepository(db)
        self.feedbacks = FeedbackRepository(db)

    async def list_conversations(self, user: RequestContext, pagination: PaginationParams) -> Page[ConversationOut]:
        items, total = await self.conversations.list_by_owner(
            user.user_id, limit=pagination.limit, offset=pagination.offset
        )
        out = [ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at) for c in items]
        return pagination.to_page(out, total)

    async def get_conversation(self, conversation_id: uuid.UUID, user: RequestContext) -> ConversationOut:
        conversation = await self._get_owned(conversation_id, user)
        return ConversationOut(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
        )

    async def list_messages(self, conversation_id: uuid.UUID, user: RequestContext) -> list[MessageOut]:
        conversation = await self._get_owned(conversation_id, user)
        rows = await self.conversations.list_messages(conversation.id)
        message_ids = [message.id for message, _ in rows]
        feedback_map = await self.feedbacks.get_user_feedback_for_messages(message_ids, user.user_id)
        return [
            MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                run_id=message.run_id,
                citations=citations,
                feedback=feedback_map.get(message.id),
            )
            for message, citations in rows
        ]

    async def rename_conversation(
        self, conversation_id: uuid.UUID, user: RequestContext, title: str
    ) -> ConversationOut:
        conversation = await self._get_owned(conversation_id, user)
        # Also marks title_generated: a manual rename must never be clobbered by a later run's
        # auto-titling (see PATCH /api/internal/conversations/{id}/title's own guard).
        await self.conversations.set_generated_title(conversation, title)
        await self.db.commit()
        await self.db.refresh(conversation, attribute_names=["updated_at"])
        return ConversationOut(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
        )

    async def delete_conversation(self, conversation_id: uuid.UUID, user: RequestContext) -> None:
        conversation = await self._get_owned(conversation_id, user)
        await self.conversations.delete(conversation)
        await self.db.commit()

    async def trigger_discussion_score(self, conversation_id: uuid.UUID, user: RequestContext) -> str:
        conversation = await self._get_owned(conversation_id, user)
        # No DiscussionScore row is created here - see DiscussionScoreRepository/worker/
        # evaluation's score_discussion, the worker posts a fully computed one back once it's
        # done. The Task row is created here directly though - same pattern as
        # EvaluationService.trigger: this request already knows the user, no round trip needed.
        celery_task_id = enqueue_score_discussion(str(conversation.id))
        await self.tasks.create(
            celery_task_id,
            SCORE_DISCUSSION_TASK,
            user.user_id,
            conversation_id=conversation.id,
        )
        await self.db.commit()
        return celery_task_id

    async def list_discussion_scores(
        self, conversation_id: uuid.UUID, user: RequestContext
    ) -> list[DiscussionScoreOut]:
        conversation = await self._get_owned(conversation_id, user)
        scores = await self.discussion_scores.list_by_conversation(conversation.id)
        return [
            DiscussionScoreOut(
                id=score.id,
                conversation_id=score.conversation_id,
                created_at=score.created_at,
                message_count=score.message_count,
                llm_model=score.llm_model,
                coherent=score.coherent,
                coherence_issues=score.coherence_issues,
                context_usage_score=score.context_usage_score,
                context_usage_issues=score.context_usage_issues,
                reasoning=score.reasoning,
            )
            for score in scores
        ]

    async def submit_discussion_feedback(
        self,
        conversation_id: uuid.UUID,
        user: RequestContext,
        rating: int,
        coherent: bool,
        context_usage_score: float | None,
        comment: str | None,
    ) -> DiscussionFeedbackOut:
        conversation = await self._get_owned(conversation_id, user)
        feedback = await self.discussion_feedbacks.upsert(
            conversation.id,
            user.user_id,
            {
                "rating": rating,
                "coherent": coherent,
                "context_usage_score": context_usage_score,
                "comment": comment,
            },
        )
        await self.db.commit()
        await self.db.refresh(feedback)
        return DiscussionFeedbackOut(
            id=feedback.id,
            conversation_id=feedback.conversation_id,
            user_id=feedback.user_id,
            rating=feedback.rating,
            coherent=feedback.coherent,
            context_usage_score=feedback.context_usage_score,
            comment=feedback.comment,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
        )

    async def list_discussion_feedback(
        self, conversation_id: uuid.UUID, user: RequestContext
    ) -> list[DiscussionFeedbackOut]:
        conversation = await self._get_owned(conversation_id, user)
        feedbacks = await self.discussion_feedbacks.list_by_conversation(conversation.id)
        return [
            DiscussionFeedbackOut(
                id=fb.id,
                conversation_id=fb.conversation_id,
                user_id=fb.user_id,
                rating=fb.rating,
                coherent=fb.coherent,
                context_usage_score=fb.context_usage_score,
                comment=fb.comment,
                created_at=fb.created_at,
                updated_at=fb.updated_at,
            )
            for fb in feedbacks
        ]

    async def _get_owned(self, conversation_id: uuid.UUID, user: RequestContext):  # noqa: ANN202
        conversation = await self.conversations.get(conversation_id, user.user_id)
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))
        return conversation
