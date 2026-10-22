import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RunSettings
from app.core.security.factory import RequestContext
from app.core.tasks import enqueue_resume_agent, enqueue_run_agent, revoke_tasks
from app.models.feedback import FeedbackSourceRole
from app.models.message import MessageRole
from app.models.run import RunStatus
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_import_repository import CollectionImportRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.schemas.run import RunCreate, RunEventOut, RunOut
from app.services.document_upload_service import _uploader_display

# Module attribute (not closed over) so tests can change the limit with monkeypatch.setattr.
_run_settings = RunSettings()


class RunNotFoundError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


class RunNotWaitingError(Exception):
    pass


class RunHasNoAnswerError(Exception):
    """The run hasn't completed with an assistant answer yet - there's nothing to attach
    feedback to (see ConversationRepository.get_assistant_message_by_run_id)."""

    pass


class RunService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = RunRepository(db)
        self.conversations = ConversationRepository(db)
        self.collections = CollectionRepository(db)
        self.hierarchy = CollectionHierarchyRepository(db)
        self.imports = CollectionImportRepository(db)
        self.feedbacks = FeedbackRepository(db)
        self.sources = SourceRepository(db)

    async def create_run(self, user: RequestContext, body: RunCreate) -> RunOut:
        if body.conversation_id is not None:
            conversation = await self.conversations.get(body.conversation_id, user.user_id)
            if conversation is None:
                raise ConversationNotFoundError(str(body.conversation_id))
        else:
            conversation = await self.conversations.create(user.user_id, title=body.query[:80])

        # The run's strong link is to this message, not directly to the
        # conversation - see app/models/run.py.
        message = await self.conversations.add_message(conversation.id, MessageRole.USER, body.query)

        # Auto-pin the conversation's temporary collection (§ conv-files, #88/#89) so the agent
        # always searches files uploaded straight into this conversation, without the user
        # having to pin it explicitly like a regular collection. None if nothing has ever been
        # uploaded into this conversation - nothing to pin, same as today.
        # Collections created from ZIPs dropped into this conversation (#223) are pinned like its
        # temporary collection below - but before resolving, so their sub-collections come along.
        imported_ids = await self.imports.root_collection_ids_for_conversation(conversation.id)
        requested_ids = list(dict.fromkeys([*(body.collection_ids or []), *imported_ids]))
        collection_ids, unexplored_ids = await self._resolve_pinned(requested_ids, user, body.include_descendants)
        temp_collection = await self.collections.get_temporary_for_conversation(conversation.id)
        if temp_collection is not None and temp_collection.id not in collection_ids:
            collection_ids.append(temp_collection.id)

        run = await self.runs.create(
            user.user_id,
            body.query,
            message.id,
            conversation.id,
            collection_ids,
            user.groups,
            body.web_search_enabled,
            user_is_admin=user.is_admin,
            user_display=_uploader_display(user),
            continue_exploration=body.continue_exploration,
            unexplored_collection_ids=unexplored_ids,
        )
        await self.db.commit()
        # Dispatched after the first commit: the worker's very first read of
        # this run (see worker/agent_execution's idempotency check) must
        # never race the row not existing yet.
        celery_task_id = enqueue_run_agent(str(run.id))
        await self.runs.set_celery_task_id(run, celery_task_id)
        await self.db.commit()
        # created_at/updated_at have a server_default/onupdate, so SQLAlchemy
        # expires them on every flush regardless of expire_on_commit - read
        # back the real value instead of lazy-loading outside a greenlet.
        await self.db.refresh(run, attribute_names=["created_at", "updated_at"])
        return self._to_out(run)

    async def _resolve_pinned(
        self, collection_ids: list[uuid.UUID], user: RequestContext, include_descendants: bool
    ) -> tuple[list[uuid.UUID], list[str]]:
        """The collections to pin for this run, and the ones left unexplored by pinning (#220).

        Pinning a collection pins the sub-collections below it too, nearest level first, up to
        PINNED_DESCENDANTS_LIMIT. What doesn't fit isn't dropped silently: the closest pinned
        ancestor of each leftover is returned as unexplored, so the answer offers to go further
        from there (#219). Only collections the user can read are expanded - a subtree is
        readable along with its root (#216), but an id they can't read stays as the caller sent it
        and is ignored by the worker, as before."""
        if not include_descendants or not collection_ids:
            return collection_ids, []

        readable = await self.collections.filter_accessible_ids(collection_ids, user.user_id, user.groups)
        descendants = await self.hierarchy.descendants_by_depth(list(readable))
        limit = _run_settings.PINNED_DESCENDANTS_LIMIT
        kept, dropped = descendants[:limit], descendants[limit:]

        pinned = list(dict.fromkeys([*collection_ids, *(collection_id for collection_id, _ in kept)]))
        searched = readable | {collection_id for collection_id, _ in kept}
        parent_of = dict(descendants)
        unexplored: dict[uuid.UUID, None] = {}
        for collection_id, _ in dropped:
            ancestor = parent_of.get(collection_id)
            # parent_of covers every descendant, so this ends at a searched collection: the
            # starting point of the walk is always one of the readable roots.
            while ancestor is not None and ancestor not in searched:
                ancestor = parent_of.get(ancestor)
            if ancestor is not None:
                unexplored[ancestor] = None
        return pinned, [str(collection_id) for collection_id in unexplored]

    async def get_run(self, run_id: uuid.UUID, user: RequestContext) -> RunOut:
        run = await self._get_owned(run_id, user)
        return self._to_out(run)

    async def list_active_runs(self, conversation_id: uuid.UUID, user: RequestContext) -> list[RunOut]:
        """Non-terminal runs for a conversation - the frontend calls this after a page
        refresh to resume polling runs that were still in progress (the assistant message
        for a running run only exists in memory, not in DB, so ensureMessagesLoaded
        can't see it). Ownership is checked via the conversation, not per-run."""
        conversation = await self.conversations.get(conversation_id, user.user_id)
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))
        active_runs = await self.runs.list_active_for_conversation(conversation.id)
        return [self._to_out(run) for run in active_runs]

    async def list_events(self, run_id: uuid.UUID, user: RequestContext, since: uuid.UUID | None) -> list[RunEventOut]:
        await self._get_owned(run_id, user)
        events = await self.runs.list_events(run_id, since)
        return [
            RunEventOut(
                id=event.id,
                task_id=event.task_id,
                type=event.type,
                data=event.data,
                created_at=event.created_at,
            )
            for event in events
        ]

    async def resume_run(self, run_id: uuid.UUID, user: RequestContext, answer: str) -> RunOut:
        run = await self._get_owned(run_id, user)
        if run.status != RunStatus.WAITING_FOR_USER:
            raise RunNotWaitingError(str(run_id))
        # Dispatched before the commit below has even run isn't safe here (unlike create_run,
        # this row already exists and the worker only reads it, doesn't idempotency-check a
        # freshly-inserted one) - order doesn't matter, so commit first for consistency with
        # create_run's "never race a read the worker might do first" reasoning anyway.
        celery_task_id = enqueue_resume_agent(str(run_id), answer)
        await self.runs.set_celery_task_id(run, celery_task_id)
        await self.db.commit()
        await self.db.refresh(run, attribute_names=["updated_at"])
        return self._to_out(run)

    async def cancel_run(self, run_id: uuid.UUID, user: RequestContext) -> RunOut:
        run = await self._get_owned(run_id, user)
        await self.runs.request_cancel(run)
        # Best-effort immediate stop if the task hasn't started a node yet;
        # the cooperative `cancel_requested` flag is what actually halts a
        # run already mid-flight (see docs/research-agent-plan.md §6).
        if run.celery_task_id:
            revoke_tasks([run.celery_task_id])
        await self.db.commit()
        await self.db.refresh(run, attribute_names=["created_at", "updated_at"])
        return self._to_out(run)

    async def submit_feedback(self, run_id: uuid.UUID, user: RequestContext, body: FeedbackCreate) -> FeedbackOut:
        # Same ownership check as every other /runs/{id} route - a reviewer giving feedback on
        # someone else's run (e.g. a support agent) isn't supported yet, see #30.
        await self._get_owned(run_id, user)
        message = await self.conversations.get_assistant_message_by_run_id(run_id)
        if message is None:
            raise RunHasNoAnswerError(str(run_id))

        # Never trust validated_source_ids at face value - only the subset actually cited on
        # this message (via message_sources) gets attached (see SourceRepository.filter_linked).
        verified_source_ids = await self.sources.filter_linked(message.id, body.validated_source_ids)
        # An added source is a brand-new suggestion, not an existing citation - always gets its
        # own Source row (deduped by url like any other, see SourceRepository.get_or_create).
        added_source_ids = [
            (await self.sources.get_or_create(added.title, added.url, None, None, None)).id
            for added in body.added_sources
        ]

        feedback = await self.feedbacks.create(
            message.id,
            user.user_id,
            body.value,
            body.reasons,
            body.comment,
            verified_source_ids,
            added_source_ids,
        )
        await self.db.commit()
        return FeedbackOut(
            id=feedback.id,
            message_id=feedback.message_id,
            value=feedback.value,
            reasons=body.reasons,
            comment=feedback.comment,
            validated_source_ids=verified_source_ids,
            added_source_ids=added_source_ids,
            created_at=feedback.created_at,
        )

    async def get_feedback(self, run_id: uuid.UUID, user: RequestContext) -> FeedbackOut | None:
        """Returns the feedback the current user left on a run's answer, or None - used to
        pre-fill the feedback modal when editing an existing negative feedback."""
        await self._get_owned(run_id, user)
        message = await self.conversations.get_assistant_message_by_run_id(run_id)
        if message is None:
            return None
        feedback = await self.feedbacks.get_user_feedback_for_message(message.id, user.user_id)
        if feedback is None:
            return None
        validated = [fs.source_id for fs in feedback.sources if fs.role == FeedbackSourceRole.VALIDATED]
        added = [fs.source_id for fs in feedback.sources if fs.role == FeedbackSourceRole.ADDED]
        return FeedbackOut(
            id=feedback.id,
            message_id=feedback.message_id,
            value=feedback.value,
            reasons=[r.reason for r in feedback.reasons],
            comment=feedback.comment,
            validated_source_ids=validated,
            added_source_ids=added,
            created_at=feedback.created_at,
        )

    async def _get_owned(self, run_id: uuid.UUID, user: RequestContext):  # noqa: ANN202
        run = await self.runs.get(run_id, user.user_id)
        if run is None:
            raise RunNotFoundError(str(run_id))
        return run

    def _to_out(self, run) -> RunOut:  # noqa: ANN001
        return RunOut(
            id=run.id,
            conversation_id=run.conversation_id,
            query=run.query,
            status=run.status,
            cancel_requested=run.cancel_requested,
            current_node=run.current_node,
            current_activity=run.current_activity,
            plan_version=run.plan_version,
            replan_count=run.replan_count,
            pending_human_action=run.pending_human_action,
            answer=run.answer,
            citations=run.citations,
            edit_proposal=run.edit_proposal,
            unexplored_collection_ids=run.unexplored_collection_ids,
            error=run.error,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
