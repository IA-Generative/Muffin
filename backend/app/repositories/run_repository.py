import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run, RunEvent, RunStatus


class RunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: str,
        query: str,
        message_id: uuid.UUID,
        conversation_id: uuid.UUID,
        pinned_collection_ids: list[uuid.UUID] | None = None,
    ) -> Run:
        run = Run(
            user_id=user_id,
            query=query,
            message_id=message_id,
            conversation_id=conversation_id,
            status=RunStatus.QUEUED,
            pinned_collection_ids=[str(cid) for cid in pinned_collection_ids] if pinned_collection_ids else None,
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def set_celery_task_id(self, run: Run, celery_task_id: str) -> None:
        run.celery_task_id = celery_task_id

    async def get(self, run_id: uuid.UUID, user_id: str) -> Run | None:
        result = await self.db.execute(select(Run).where(Run.id == run_id, Run.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, run_id: uuid.UUID) -> Run | None:
        """No owner check - internal/worker use only, never exposed on a
        user-facing route (mirrors CollectionRepository.get_by_id)."""
        result = await self.db.execute(select(Run).where(Run.id == run_id))
        return result.scalar_one_or_none()

    async def request_cancel(self, run: Run) -> None:
        run.cancel_requested = True

    async def update_status(
        self, run: Run, status: RunStatus, current_node: str | None, current_activity: str | None
    ) -> None:
        run.status = status
        if current_node is not None:
            run.current_node = current_node
        if current_activity is not None:
            run.current_activity = current_activity

    async def update_state(
        self,
        run: Run,
        research_plan: dict[str, Any] | None,
        budget: dict[str, Any] | None,
        pending_human_action: dict[str, Any] | None,
        plan_version: int | None,
        replan_count: int | None,
    ) -> None:
        if research_plan is not None:
            run.research_plan = {**(run.research_plan or {}), **research_plan}
        if budget is not None:
            run.budget = {**(run.budget or {}), **budget}
        if pending_human_action is not None:
            run.pending_human_action = pending_human_action
        if plan_version is not None:
            run.plan_version = plan_version
        if replan_count is not None:
            run.replan_count = replan_count

    async def set_result(self, run: Run, answer: str, citations: list[dict[str, Any]]) -> None:
        run.answer = answer
        run.citations = citations

    async def set_error(self, run: Run, error: str) -> None:
        run.error = error

    async def list_events(self, run_id: uuid.UUID, since: uuid.UUID | None = None) -> Sequence[RunEvent]:
        query = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.created_at)
        if since is not None:
            anchor = await self.db.scalar(select(RunEvent.created_at).where(RunEvent.id == since))
            if anchor is not None:
                query = query.where(RunEvent.created_at > anchor)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def add_event(
        self, run_id: uuid.UUID, type_: str, data: dict[str, Any] | None = None, task_id: str | None = None
    ) -> RunEvent:
        event = RunEvent(run_id=run_id, type=type_, data=data, task_id=task_id)
        self.db.add(event)
        await self.db.flush()
        return event
