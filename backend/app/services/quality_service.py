"""Quality service: cross-collection aggregation for the /quality dashboard (see #33).

Aggregates four metric families:
- retrieval: latest EvaluationRun per collection (see #11)
- feedback: thumbs up/down counts (see #30)
- discussion: DiscussionScore + DiscussionFeedback aggregates (see #31)
- groundedness: Run.grounding_valid aggregates (see #32)

Admin scope: all collections, all conversations.
User scope: only the user's own collections and conversations.
"""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import enqueue_score_discussion
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.discussion_feedback import DiscussionFeedback
from app.models.discussion_score import DiscussionScore
from app.models.evaluation import EvaluationRun
from app.models.message import Message
from app.models.run import Run
from app.schemas.quality import (
    ConversationWithScoreOut,
    DiscussionMetricOut,
    DiscussionScoreEntry,
    FeedbackMetricOut,
    GroundednessMetricOut,
    QualityOverviewOut,
    RetrievalMetricOut,
)

# Same citations[].vdb_id matching as FeedbackRepository - the only real link between a run
# and a collection.
_CITED_COLLECTION = (
    "EXISTS (SELECT 1 FROM jsonb_array_elements(runs.citations) AS c WHERE c ->> 'vdb_id' = :collection_id)"
)


class QualityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_overview(
        self,
        user: RequestContext,
        collection_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 10,
        model_filter: str | None = None,
    ) -> QualityOverviewOut:
        """When collection_id is None and user is admin, aggregates across all collections.
        When collection_id is set, scopes to that collection (with access check).
        When collection_id is None and user is not admin, scopes to their own collections.
        When model_filter is set, only conversations whose latest score used that model are
        listed in the conversations table (the aggregate metrics above are unaffected).
        """
        if collection_id is not None:
            # Per-collection: verify access via the collection's existence and ownership
            col = await self.db.scalar(select(Collection).where(Collection.id == collection_id))
            if col is None:
                raise CollectionNotFoundError(str(collection_id))
            if col.owner_id != user.user_id and not user.is_admin:
                # Check if shared with this user
                from app.repositories.collection_repository import CollectionRepository

                accessible = await CollectionRepository(self.db).get_accessible(
                    collection_id, user.user_id, user.groups
                )
                if accessible is None:
                    raise CollectionNotFoundError(str(collection_id))

        retrieval = await self._get_retrieval_metrics(user, collection_id)
        feedback = await self._get_feedback_metrics(user, collection_id)
        discussion = await self._get_discussion_metrics(user, collection_id, model_filter)
        groundedness = await self._get_groundedness_metrics(user, collection_id)
        conversations, total = await self._get_conversations_with_scores(
            user, collection_id, page, page_size, model_filter
        )

        return QualityOverviewOut(
            retrieval=retrieval,
            feedback=feedback,
            discussion=discussion,
            groundedness=groundedness,
            conversations=conversations,
            conversations_total=total,
            conversations_page=page,
        )

    async def _get_retrieval_metrics(
        self, user: RequestContext, collection_id: uuid.UUID | None
    ) -> list[RetrievalMetricOut]:
        """Latest evaluation run per collection - one row per collection that has at least one run."""
        # Subquery: the latest run per collection
        latest_run_sq = (
            select(
                EvaluationRun.collection_id,
                func.max(EvaluationRun.created_at).label("max_created"),
            )
            .group_by(EvaluationRun.collection_id)
            .subquery()
        )

        query = (
            select(EvaluationRun, Collection.name)
            .join(Collection, EvaluationRun.collection_id == Collection.id)
            .join(
                latest_run_sq,
                (EvaluationRun.collection_id == latest_run_sq.c.collection_id)
                & (EvaluationRun.created_at == latest_run_sq.c.max_created),
            )
        )

        if collection_id is not None:
            query = query.where(EvaluationRun.collection_id == collection_id)
        elif not user.is_admin:
            # Non-admin: only their own collections
            query = query.where(Collection.owner_id == user.user_id)

        query = query.order_by(EvaluationRun.created_at.desc())
        result = await self.db.execute(query)
        return [
            RetrievalMetricOut(
                collection_id=run.collection_id,
                collection_name=name,
                run_id=run.id,
                created_at=run.created_at,
                pair_count=run.pair_count,
                precision_at_k=run.precision_at_k,
                recall_at_k=run.recall_at_k,
                mrr=run.mrr,
                ndcg=run.ndcg,
            )
            for run, name in result.all()
        ]

    async def _get_feedback_metrics(self, user: RequestContext, collection_id: uuid.UUID | None) -> FeedbackMetricOut:
        """Aggregates feedback (thumbs up/down) across all messages whose run cited the scoped collections.
        Uses raw SQL to match the pattern in FeedbackRepository.get_stats - mixing ORM select() with
        text() WHERE clauses on JSONB doesn't work cleanly in SQLAlchemy."""
        scope_clause = ""
        params: dict[str, str] = {}

        if collection_id is not None:
            scope_clause = f"AND {_CITED_COLLECTION}"
            params["collection_id"] = str(collection_id)
        elif not user.is_admin:
            scope_clause = (
                "AND EXISTS (SELECT 1 FROM collections "
                "WHERE collections.owner_id = :owner_id "
                "AND EXISTS (SELECT 1 FROM jsonb_array_elements(runs.citations) AS c "
                "WHERE c ->> 'vdb_id' = collections.id::text))"
            )
            params["owner_id"] = user.user_id

        counts_sql = text(f"""
            SELECT
                count(*) FILTER (WHERE feedbacks.value = 'UP') AS up_count,
                count(*) FILTER (WHERE feedbacks.value = 'DOWN') AS down_count
            FROM feedbacks
            JOIN messages ON messages.id = feedbacks.message_id
            JOIN runs ON runs.id = messages.run_id
            WHERE 1=1 {scope_clause}
        """).bindparams(**params)
        counts_result = await self.db.execute(counts_sql)
        row = counts_result.one()
        up_count = row.up_count or 0
        down_count = row.down_count or 0

        reason_sql = text(f"""
            SELECT feedback_reasons.reason AS reason, count(*) AS count
            FROM feedback_reasons
            JOIN feedbacks ON feedbacks.id = feedback_reasons.feedback_id
            JOIN messages ON messages.id = feedbacks.message_id
            JOIN runs ON runs.id = messages.run_id
            WHERE feedbacks.value = 'DOWN' {scope_clause}
            GROUP BY feedback_reasons.reason
        """).bindparams(**params)
        reason_result = await self.db.execute(reason_sql)
        reason_counts = {row.reason: row.count for row in reason_result.all()}

        return FeedbackMetricOut(
            up_count=up_count,
            down_count=down_count,
            reason_counts=reason_counts,
        )

    async def _get_discussion_metrics(
        self,
        user: RequestContext,
        collection_id: uuid.UUID | None,
        model_filter: str | None = None,
    ) -> DiscussionMetricOut:
        """Aggregates DiscussionScore and DiscussionFeedback across scoped conversations.

        When model_filter is set, only scores from that model are counted in the
        aggregates, and total_conversations is the number of conversations that
        have at least one score with that model."""
        # For discussion metrics, we scope by conversation ownership (not collection),
        # since discussions are per-user, not per-collection.
        conv_query = select(Conversation.id)
        if not user.is_admin:
            conv_query = conv_query.where(Conversation.user_id == user.user_id)

        # If collection_id is set, filter to conversations whose runs cited that collection
        if collection_id is not None:
            conv_query = conv_query.where(
                Conversation.id.in_(
                    select(Message.conversation_id)
                    .join(Run, Run.id == Message.run_id)
                    .where(text(_CITED_COLLECTION).bindparams(collection_id=str(collection_id)))
                )
            )

        conv_result = await self.db.execute(conv_query)
        conv_ids = [row[0] for row in conv_result.all()]

        if not conv_ids:
            return DiscussionMetricOut(
                total_conversations=0,
                coherent_count=0,
                avg_context_usage_score=None,
                avg_rating=None,
            )

        # When filtering by model, only consider scores from that model.
        # Otherwise, use the latest score per conversation (across all models).
        if model_filter is not None:
            scores_query = select(DiscussionScore).where(
                DiscussionScore.conversation_id.in_(conv_ids) & (DiscussionScore.llm_model == model_filter)
            )
            scores_result = await self.db.execute(scores_query)
            scores = scores_result.scalars().all()
            total = len(scores)
        else:
            # Latest score per conversation
            latest_score_sq = (
                select(
                    DiscussionScore.conversation_id,
                    func.max(DiscussionScore.created_at).label("max_created"),
                )
                .where(DiscussionScore.conversation_id.in_(conv_ids))
                .group_by(DiscussionScore.conversation_id)
                .subquery()
            )

            scores_query = select(DiscussionScore).join(
                latest_score_sq,
                (DiscussionScore.conversation_id == latest_score_sq.c.conversation_id)
                & (DiscussionScore.created_at == latest_score_sq.c.max_created),
            )
            scores_result = await self.db.execute(scores_query)
            scores = scores_result.scalars().all()
            total = len(conv_ids)

        coherent_count = sum(1 for s in scores if s.coherent)
        context_scores = [s.context_usage_score for s in scores]
        avg_context = sum(context_scores) / len(context_scores) if context_scores else None

        # Human feedback: latest per conversation
        latest_feedback_sq = (
            select(
                DiscussionFeedback.conversation_id,
                func.max(DiscussionFeedback.updated_at).label("max_updated"),
            )
            .where(DiscussionFeedback.conversation_id.in_(conv_ids))
            .group_by(DiscussionFeedback.conversation_id)
            .subquery()
        )

        feedback_query = select(DiscussionFeedback).join(
            latest_feedback_sq,
            (DiscussionFeedback.conversation_id == latest_feedback_sq.c.conversation_id)
            & (DiscussionFeedback.updated_at == latest_feedback_sq.c.max_updated),
        )
        feedback_result = await self.db.execute(feedback_query)
        feedbacks = feedback_result.scalars().all()
        ratings = [f.rating for f in feedbacks]
        avg_rating = sum(ratings) / len(ratings) if ratings else None

        return DiscussionMetricOut(
            total_conversations=total,
            coherent_count=coherent_count,
            avg_context_usage_score=avg_context,
            avg_rating=avg_rating,
        )

    async def _get_groundedness_metrics(
        self, user: RequestContext, collection_id: uuid.UUID | None
    ) -> GroundednessMetricOut:
        """Aggregates Run.grounding_valid across scoped runs. Uses raw SQL to match the pattern
        in FeedbackRepository.get_stats - JSONB citations filtering doesn't mix with ORM select().
        """
        scope_clause = ""
        params: dict[str, str] = {}

        if collection_id is not None:
            scope_clause = f"AND {_CITED_COLLECTION}"
            params["collection_id"] = str(collection_id)
        elif not user.is_admin:
            scope_clause = (
                "AND EXISTS (SELECT 1 FROM collections "
                "WHERE collections.owner_id = :owner_id "
                "AND EXISTS (SELECT 1 FROM jsonb_array_elements(runs.citations) AS c "
                "WHERE c ->> 'vdb_id' = collections.id::text))"
            )
            params["owner_id"] = user.user_id

        sql = text(f"""
            SELECT
                count(*) FILTER (WHERE runs.grounding_valid IS NOT NULL) AS evaluated_count,
                count(*) FILTER (WHERE runs.grounding_valid = false) AS ungrounded_count
            FROM runs
            WHERE 1=1 {scope_clause}
        """).bindparams(**params)
        result = await self.db.execute(sql)
        row = result.one()
        return GroundednessMetricOut(
            evaluated_count=row.evaluated_count or 0,
            ungrounded_count=row.ungrounded_count or 0,
        )

    async def _get_conversations_with_scores(
        self,
        user: RequestContext,
        collection_id: uuid.UUID | None,
        page: int = 1,
        page_size: int = 10,
        model_filter: str | None = None,
    ) -> tuple[list[ConversationWithScoreOut], int]:
        """Lists conversations with their latest LLM score and human feedback, most recent first.
        Returns (page_items, total_count).

        When model_filter is set, only conversations whose latest DiscussionScore used that
        model are returned (conversations with no score at all are excluded)."""
        query = select(Conversation)
        if not user.is_admin:
            query = query.where(Conversation.user_id == user.user_id)

        if collection_id is not None:
            query = query.where(
                Conversation.id.in_(
                    select(Message.conversation_id)
                    .join(Run, Run.id == Message.run_id)
                    .where(text(_CITED_COLLECTION).bindparams(collection_id=str(collection_id)))
                )
            )

        # When filtering by model, restrict to conversations that have at least one
        # score with that model. The displayed score will be the one from that model
        # (see below), not necessarily the latest across all models.
        if model_filter is not None:
            query = query.where(
                Conversation.id.in_(
                    select(DiscussionScore.conversation_id).where(DiscussionScore.llm_model == model_filter)
                )
            )

        # Total count (before pagination)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Paginated results
        offset = (page - 1) * page_size
        query = query.order_by(Conversation.updated_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        conversations = result.scalars().all()

        if not conversations:
            return [], total

        conv_ids = [c.id for c in conversations]
        # Message counts per conversation
        msg_count_query = (
            select(Message.conversation_id, func.count().label("count"))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        )
        msg_counts = {row.conversation_id: row.count for row in (await self.db.execute(msg_count_query)).all()}

        # Latest score per conversation (for the top-level convenience fields).
        # When filtering by model, the "latest" score is the latest from that
        # specific model. Otherwise, it's the latest across all models.
        if model_filter is not None:
            latest_score_sq = (
                select(
                    DiscussionScore.conversation_id,
                    func.max(DiscussionScore.created_at).label("max_created"),
                )
                .where(DiscussionScore.conversation_id.in_(conv_ids) & (DiscussionScore.llm_model == model_filter))
                .group_by(DiscussionScore.conversation_id)
                .subquery()
            )
        else:
            latest_score_sq = (
                select(
                    DiscussionScore.conversation_id,
                    func.max(DiscussionScore.created_at).label("max_created"),
                )
                .where(DiscussionScore.conversation_id.in_(conv_ids))
                .group_by(DiscussionScore.conversation_id)
                .subquery()
            )
        scores_query = select(DiscussionScore).join(
            latest_score_sq,
            (DiscussionScore.conversation_id == latest_score_sq.c.conversation_id)
            & (DiscussionScore.created_at == latest_score_sq.c.max_created),
        )
        latest_scores = {s.conversation_id: s for s in (await self.db.execute(scores_query)).scalars().all()}

        # ALL scores per conversation (for the expandable detail rows)
        all_scores_query = (
            select(DiscussionScore)
            .where(DiscussionScore.conversation_id.in_(conv_ids))
            .order_by(DiscussionScore.created_at.desc())
        )
        all_scores: dict[uuid.UUID, list[DiscussionScore]] = {}
        for s in (await self.db.execute(all_scores_query)).scalars().all():
            all_scores.setdefault(s.conversation_id, []).append(s)

        # Latest feedback per conversation
        latest_feedback_sq = (
            select(
                DiscussionFeedback.conversation_id,
                func.max(DiscussionFeedback.updated_at).label("max_updated"),
            )
            .where(DiscussionFeedback.conversation_id.in_(conv_ids))
            .group_by(DiscussionFeedback.conversation_id)
            .subquery()
        )
        feedback_query = select(DiscussionFeedback).join(
            latest_feedback_sq,
            (DiscussionFeedback.conversation_id == latest_feedback_sq.c.conversation_id)
            & (DiscussionFeedback.updated_at == latest_feedback_sq.c.max_updated),
        )
        feedbacks = {f.conversation_id: f for f in (await self.db.execute(feedback_query)).scalars().all()}

        items = [
            ConversationWithScoreOut(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                message_count=msg_counts.get(conv.id, 0),
                coherent=(latest_scores[conv.id].coherent if conv.id in latest_scores else None),
                context_usage_score=(latest_scores[conv.id].context_usage_score if conv.id in latest_scores else None),
                llm_model=(latest_scores[conv.id].llm_model if conv.id in latest_scores else None),
                scores=[
                    DiscussionScoreEntry(
                        id=s.id,
                        created_at=s.created_at,
                        llm_model=s.llm_model,
                        message_count=s.message_count,
                        coherent=s.coherent,
                        context_usage_score=s.context_usage_score,
                    )
                    for s in all_scores.get(conv.id, [])
                ],
                human_rating=(feedbacks[conv.id].rating if conv.id in feedbacks else None),
                human_coherent=(feedbacks[conv.id].coherent if conv.id in feedbacks else None),
            )
            for conv in conversations
        ]
        return items, total

    async def trigger_discussion_score(
        self,
        conversation_id: uuid.UUID,
        user: RequestContext,
        model: str | None = None,
    ) -> str:
        """Triggers an LLM judgment of a conversation - admin can score any conversation,
        non-admin only their own. When `model` is None, the worker picks the hub's default chat
        model; when set, that specific model is used (the unique index on
        (conversation, content_hash, model) means re-scoring with a different model creates a
        new score row instead of being a no-op)."""
        conv = await self.db.scalar(select(Conversation).where(Conversation.id == conversation_id))
        if conv is None:
            raise ConversationNotFoundError(str(conversation_id))
        if conv.user_id != user.user_id and not user.is_admin:
            raise ConversationNotFoundError(str(conversation_id))

        from app.core.tasks import SCORE_DISCUSSION_TASK
        from app.repositories.task_repository import TaskRepository

        celery_task_id = enqueue_score_discussion(str(conv.id), model)
        tasks = TaskRepository(self.db)
        await tasks.create(
            celery_task_id,
            SCORE_DISCUSSION_TASK,
            user.user_id,
            conversation_id=conv.id,
        )
        await self.db.commit()
        return celery_task_id

    async def trigger_score_all(
        self,
        user: RequestContext,
        collection_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> list[str]:
        """Triggers LLM scoring for all conversations that don't have a score yet (or, when
        `model` is set, all conversations that don't have a score with that specific model).
        Admin: all conversations (optionally scoped by collection_id).
        Non-admin: only their own conversations."""
        # When a model is specified, skip conversations that already have a score
        # with that exact model (the worker's dedup would skip them anyway, but
        # this avoids enqueuing unnecessary tasks).
        if model is not None:
            scored_conv_ids = select(DiscussionScore.conversation_id).where(DiscussionScore.llm_model == model)
        else:
            scored_conv_ids = select(DiscussionScore.conversation_id)

        query = select(Conversation).where(~Conversation.id.in_(scored_conv_ids))
        if not user.is_admin:
            query = query.where(Conversation.user_id == user.user_id)

        if collection_id is not None:
            query = query.where(
                Conversation.id.in_(
                    select(Message.conversation_id)
                    .join(Run, Run.id == Message.run_id)
                    .where(text(_CITED_COLLECTION).bindparams(collection_id=str(collection_id)))
                )
            )

        result = await self.db.execute(query)
        conversations = result.scalars().all()

        if not conversations:
            return []

        from app.core.tasks import SCORE_DISCUSSION_TASK
        from app.repositories.task_repository import TaskRepository

        tasks = TaskRepository(self.db)
        celery_task_ids: list[str] = []
        for conv in conversations:
            celery_task_id = enqueue_score_discussion(str(conv.id), model)
            await tasks.create(
                celery_task_id,
                SCORE_DISCUSSION_TASK,
                user.user_id,
                conversation_id=conv.id,
            )
            celery_task_ids.append(celery_task_id)

        await self.db.commit()
        return celery_task_ids


class CollectionNotFoundError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass
