import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import enqueue_resume_agent, enqueue_run_agent, revoke_task
from app.models.message import MessageRole
from app.models.run import RunStatus
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.run_repository import RunRepository
from app.schemas.run import RunCreate, RunEventOut, RunOut


class RunNotFoundError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


class RunNotWaitingError(Exception):
    pass


class RunService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = RunRepository(db)
        self.conversations = ConversationRepository(db)

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
        run = await self.runs.create(user.user_id, body.query, message.id, conversation.id)
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

    async def get_run(self, run_id: uuid.UUID, user: RequestContext) -> RunOut:
        run = await self._get_owned(run_id, user)
        return self._to_out(run)

    async def list_events(self, run_id: uuid.UUID, user: RequestContext, since: uuid.UUID | None) -> list[RunEventOut]:
        await self._get_owned(run_id, user)
        events = await self.runs.list_events(run_id, since)
        return [
            RunEventOut(
                id=event.id, task_id=event.task_id, type=event.type, data=event.data, created_at=event.created_at
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
            revoke_task(run.celery_task_id)
        await self.db.commit()
        await self.db.refresh(run, attribute_names=["created_at", "updated_at"])
        return self._to_out(run)

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
            error=run.error,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
