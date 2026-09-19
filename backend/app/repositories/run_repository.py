import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, text
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
        user_groups: list[str] | None = None,
        web_search_enabled: bool = False,
    ) -> Run:
        run = Run(
            user_id=user_id,
            query=query,
            message_id=message_id,
            conversation_id=conversation_id,
            status=RunStatus.QUEUED,
            pinned_collection_ids=([str(cid) for cid in pinned_collection_ids] if pinned_collection_ids else None),
            user_groups=user_groups or None,
            web_search_enabled=web_search_enabled,
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

    async def list_active_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[Run]:
        """Non-terminal runs for a conversation - used by the frontend after a page
        refresh to resume polling runs that were still in progress when the browser
        lost its in-memory placeholder assistant message (see ensureMessagesLoaded)."""
        result = await self.db.execute(
            select(Run)
            .where(
                Run.conversation_id == conversation_id,
                Run.status.notin_([RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED]),
            )
            .order_by(Run.created_at)
        )
        return result.scalars().all()

    async def request_cancel(self, run: Run) -> None:
        run.cancel_requested = True

    async def update_status(
        self,
        run: Run,
        status: RunStatus,
        current_node: str | None,
        current_activity: str | None,
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

    async def set_result(
        self,
        run: Run,
        answer: str,
        citations: list[dict[str, Any]],
        grounding_valid: bool | None = None,
        grounding_unsupported_claims: list[str] | None = None,
        grounding_research_count: int | None = None,
    ) -> None:
        run.answer = answer
        run.citations = citations
        run.grounding_valid = grounding_valid
        run.grounding_unsupported_claims = grounding_unsupported_claims
        run.grounding_research_count = grounding_research_count

    async def set_error(self, run: Run, error: str) -> None:
        run.error = error

    async def get_groundedness_stats(self, collection_id: uuid.UUID) -> dict[str, Any]:
        """Aggregates the grounding verdicts (see Run.grounding_valid) of every completed run
        that cited this collection - identified via citations[].vdb_id, the only link between a
        run and a collection (a run's pinned_collection_ids is what the user attached, not
        necessarily what actually got searched/cited - see worker/agent_execution/app/graph/
        nodes/research_task.py). No dedicated join table for this, jsonb_array_elements is cheap
        enough at this scale and avoids a schema change just to index an already-denormalized
        JSONB column."""
        cited_filter = text(
            "EXISTS (SELECT 1 FROM jsonb_array_elements(runs.citations) AS c WHERE c ->> 'vdb_id' = :collection_id)"
        ).bindparams(collection_id=str(collection_id))

        counts = await self.db.execute(
            select(
                func.count().filter(Run.grounding_valid.is_not(None)).label("evaluated_count"),
                func.count().filter(Run.grounding_valid.is_(False)).label("ungrounded_count"),
            ).where(cited_filter)
        )
        evaluated_count, ungrounded_count = counts.one()

        recent = await self.db.execute(
            select(Run.id, Run.query, Run.created_at, Run.grounding_unsupported_claims)
            .where(cited_filter, Run.grounding_valid.is_(False))
            .order_by(Run.created_at.desc())
            .limit(10)
        )
        recent_ungrounded = [
            {
                "run_id": row.id,
                "query": row.query,
                "created_at": row.created_at,
                "unsupported_claims": row.grounding_unsupported_claims or [],
            }
            for row in recent
        ]
        return {
            "evaluated_count": evaluated_count or 0,
            "ungrounded_count": ungrounded_count or 0,
            "recent_ungrounded": recent_ungrounded,
        }

    async def list_events(self, run_id: uuid.UUID, since: uuid.UUID | None = None) -> Sequence[RunEvent]:
        query = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.created_at)
        if since is not None:
            anchor = await self.db.scalar(select(RunEvent.created_at).where(RunEvent.id == since))
            if anchor is not None:
                query = query.where(RunEvent.created_at > anchor)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def add_event(
        self,
        run_id: uuid.UUID,
        type_: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> RunEvent:
        event = RunEvent(run_id=run_id, type=type_, data=data, task_id=task_id)
        self.db.add(event)
        await self.db.flush()
        return event
