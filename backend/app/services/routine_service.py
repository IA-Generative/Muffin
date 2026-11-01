import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import routine_schedule
from app.core.security.factory import RequestContext
from app.models.routine import (
    Routine,
    RoutineCondition,
    RoutineRun,
    RoutineSettings,
    RoutineState,
)
from app.repositories.collection_repository import CollectionRepository
from app.repositories.routine_repository import RoutineRepository
from app.schemas.pagination import Page, PaginationParams
from app.schemas.routine import (
    PreviewOut,
    RoutineCreate,
    RoutineOut,
    RoutineRunOut,
    RoutineStatusOut,
    RoutineUpdate,
    ScheduleIn,
    ScheduleOut,
)
from app.services.assistant_service import AssistantNotFoundError, AssistantService, NoReadableCollectionError
from app.services.routine_runner import RoutineExecutor, schedule_of, suspend

PREVIEW_DATES = 5


class RoutineError(Exception):
    """A request that is refused, said with a code that does not change and words for the person. `status` is the HTTP
    status the API answers with."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class RoutineNotFoundError(Exception):
    pass


def _display(user: RequestContext) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email or user.user_id


def _schedule_from(body: ScheduleIn) -> routine_schedule.Schedule:
    return routine_schedule.Schedule(
        kind=body.kind,
        timezone=body.timezone,
        interval_minutes=body.interval_minutes,
        time_of_day=body.time_of_day,
        weekdays=sorted(set(body.weekdays)) if body.weekdays else None,
        day_of_month=body.day_of_month,
    )


def present_run(run: RoutineRun) -> RoutineRunOut:
    duration = int((run.finished_at - run.started_at).total_seconds()) if run.finished_at else None
    return RoutineRunOut(
        id=run.id,
        status=run.status,
        skip_reason=run.skip_reason,
        trigger=run.trigger,
        error=run.error,
        note=run.note,
        total_tokens=run.total_tokens,
        conversation_id=run.conversation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=duration,
    )


def present(routine: Routine, last_run: RoutineRun | None) -> RoutineOut:
    return RoutineOut(
        id=routine.id,
        name=routine.name,
        question=routine.question,
        collection_ids=[uuid.UUID(collection_id) for collection_id in routine.collection_ids],
        include_descendants=routine.include_descendants,
        assistant_id=routine.assistant_id,
        web_search=routine.web_search,
        schedule=ScheduleOut(
            kind=routine.kind,
            timezone=routine.timezone,
            interval_minutes=routine.interval_minutes,
            time_of_day=routine.time_of_day,
            weekdays=list(routine.weekdays) if routine.weekdays else None,
            day_of_month=routine.day_of_month,
        ),
        condition=routine.condition,
        result_mode=routine.result_mode,
        notify=routine.notify,
        state=routine.state,
        suspended_reason=routine.suspended_reason,
        next_run_at=routine.next_run_at,
        last_run_at=routine.last_run_at,
        consecutive_failures=routine.consecutive_failures,
        conversation_id=routine.conversation_id,
        last_run=present_run(last_run) if last_run else None,
        created_at=routine.created_at,
    )


class RoutineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.routines = RoutineRepository(db)
        self.collections = CollectionRepository(db)

    async def status(self, user: RequestContext) -> RoutineStatusOut:
        settings = await self.routines.settings()
        await self.db.commit()
        return RoutineStatusOut(
            enabled=settings.enabled,
            max_active=settings.max_active_per_user,
            min_interval_minutes=settings.min_interval_minutes,
            max_runs_per_day=settings.max_runs_per_user_per_day,
            active=await self.routines.count_active(user.user_id),
            runs_today=await self.routines.count_runs_since(user.user_id, datetime.now(UTC) - timedelta(days=1)),
        )

    async def mine(self, user: RequestContext) -> list[RoutineOut]:
        rows = await self.routines.list_owned(user.user_id)
        last = await self.routines.last_runs([row.id for row in rows])
        return [present(row, last.get(row.id)) for row in rows]

    async def get(self, user: RequestContext, routine_id: uuid.UUID) -> RoutineOut:
        routine = await self._owned(user, routine_id)
        return present(routine, (await self.routines.last_runs([routine.id])).get(routine.id))

    async def create(self, user: RequestContext, body: RoutineCreate) -> RoutineOut:
        settings = await self._enabled()
        schedule = self._valid_schedule(body.schedule, settings)
        await self._valid_scope(user, body.collection_ids, body.assistant_id, body.condition, body.question)
        if await self.routines.count_active(user.user_id) >= settings.max_active_per_user:
            raise RoutineError(
                "trop_de_routines", f"Vous pouvez avoir {settings.max_active_per_user} routines actives au plus.", 409
            )
        routine = await self.routines.add(
            Routine(
                owner_id=user.user_id,
                owner_display=_display(user),
                name=body.name.strip(),
                question=body.question.strip(),
                collection_ids=[str(collection_id) for collection_id in dict.fromkeys(body.collection_ids)],
                include_descendants=body.include_descendants,
                assistant_id=body.assistant_id,
                web_search=body.web_search,
                kind=schedule.kind,
                interval_minutes=schedule.interval_minutes,
                time_of_day=schedule.time_of_day,
                weekdays=list(schedule.weekdays) if schedule.weekdays else None,
                day_of_month=schedule.day_of_month,
                timezone=schedule.timezone,
                condition=body.condition,
                result_mode=body.result_mode,
                notify=body.notify,
                state=RoutineState.ACTIVE,
                next_run_at=routine_schedule.first_run(schedule, datetime.now(UTC)),
                # What is new is counted from now on, not from the beginning of time.
                last_checked_at=datetime.now(UTC),
            )
        )
        await self.db.commit()
        return present(routine, None)

    async def update(self, user: RequestContext, routine_id: uuid.UUID, body: RoutineUpdate) -> RoutineOut:
        routine = await self._owned(user, routine_id)
        settings = await self.routines.settings()
        if routine.state == RoutineState.SUSPENDED and routine.suspended_reason == "admin":
            raise RoutineError("suspendue_par_un_administrateur", "Un administrateur a suspendu cette routine.", 409)
        collection_ids = (
            body.collection_ids
            if body.collection_ids is not None
            else [uuid.UUID(collection_id) for collection_id in routine.collection_ids]
        )
        assistant_id = (
            None if body.clear_assistant else (body.assistant_id if body.assistant_id else routine.assistant_id)
        )
        condition = body.condition or routine.condition
        question = body.question.strip() if body.question else routine.question
        await self._valid_scope(user, collection_ids, assistant_id, condition, question)
        if body.schedule is not None:
            schedule = self._valid_schedule(body.schedule, settings)
            routine.kind = schedule.kind
            routine.interval_minutes = schedule.interval_minutes
            routine.time_of_day = schedule.time_of_day
            routine.weekdays = list(schedule.weekdays) if schedule.weekdays else None
            routine.day_of_month = schedule.day_of_month
            routine.timezone = schedule.timezone
            if routine.state == RoutineState.ACTIVE:
                routine.next_run_at = routine_schedule.first_run(schedule, datetime.now(UTC))
        if body.name is not None:
            routine.name = body.name.strip()
        routine.question = question
        routine.collection_ids = [str(collection_id) for collection_id in dict.fromkeys(collection_ids)]
        routine.assistant_id = assistant_id
        for field in ("include_descendants", "web_search", "condition", "result_mode", "notify"):
            value = getattr(body, field)
            if value is not None:
                setattr(routine, field, value)
        await self.db.commit()
        await self.db.refresh(routine)
        return present(routine, (await self.routines.last_runs([routine.id])).get(routine.id))

    async def delete(self, user: RequestContext, routine_id: uuid.UUID) -> None:
        routine = await self._owned(user, routine_id)
        await self.routines.delete(routine)
        await self.db.commit()

    async def pause(self, user: RequestContext, routine_id: uuid.UUID) -> RoutineOut:
        routine = await self._owned(user, routine_id)
        if routine.state == RoutineState.ACTIVE:
            routine.state = RoutineState.PAUSED
            routine.next_run_at = None
            await self.db.commit()
        return await self.get(user, routine_id)

    async def resume(self, user: RequestContext, routine_id: uuid.UUID) -> RoutineOut:
        settings = await self._enabled()
        routine = await self._owned(user, routine_id)
        if routine.state == RoutineState.SUSPENDED and routine.suspended_reason == "admin":
            raise RoutineError("suspendue_par_un_administrateur", "Un administrateur a suspendu cette routine.", 409)
        if routine.state != RoutineState.ACTIVE:
            if await self.routines.count_active(user.user_id) >= settings.max_active_per_user:
                raise RoutineError(
                    "trop_de_routines",
                    f"Vous pouvez avoir {settings.max_active_per_user} routines actives au plus.",
                    409,
                )
            routine.state = RoutineState.ACTIVE
            routine.suspended_reason = None
            routine.consecutive_failures = 0
            routine.last_checked_at = datetime.now(UTC)
            routine.next_run_at = routine_schedule.first_run(schedule_of(routine), datetime.now(UTC))
            await self.db.commit()
        return await self.get(user, routine_id)

    async def run_now(self, user: RequestContext, routine_id: uuid.UUID) -> RoutineRunOut:
        """Tries a routine without waiting for its date. The condition "only if there is something new" does not apply:
        the person wants to see what it does. The limits do - they are what the cost is bounded by."""
        await self._enabled()
        routine = await self._owned(user, routine_id)
        if routine.state == RoutineState.SUSPENDED and routine.suspended_reason == "admin":
            raise RoutineError("suspendue_par_un_administrateur", "Un administrateur a suspendu cette routine.", 409)
        await self.db.rollback()
        entry = await RoutineExecutor(self.db).launch(routine_id, "manual")
        if entry is None:
            raise RoutineNotFoundError(str(routine_id))
        return present_run(entry)

    async def runs(
        self, user: RequestContext, routine_id: uuid.UUID, pagination: PaginationParams
    ) -> Page[RoutineRunOut]:
        routine = await self._owned(user, routine_id)
        rows, total = await self.routines.list_runs(routine.id, pagination.limit, pagination.offset)
        return pagination.to_page([present_run(row) for row in rows], total)

    async def preview(self, user: RequestContext, body: ScheduleIn) -> PreviewOut:
        """The next dates of a rhythm, for the person to check it before keeping it."""
        settings = await self.routines.settings()
        schedule = self._valid_schedule(body, settings)
        return PreviewOut(dates=routine_schedule.upcoming(schedule, datetime.now(UTC), PREVIEW_DATES))

    # --- what is checked ---

    async def _enabled(self) -> RoutineSettings:
        settings = await self.routines.settings()
        if not settings.enabled:
            raise RoutineError("fonction_desactivee", "Les routines ne sont pas activées.", 404)
        return settings

    async def _owned(self, user: RequestContext, routine_id: uuid.UUID) -> Routine:
        routine = await self.routines.get_owned(routine_id, user.user_id)
        if routine is None:
            raise RoutineNotFoundError(str(routine_id))
        return routine

    @staticmethod
    def _valid_schedule(body: ScheduleIn, settings: RoutineSettings) -> routine_schedule.Schedule:
        schedule = _schedule_from(body)
        try:
            routine_schedule.validate(schedule, settings.min_interval_minutes)
        except routine_schedule.InvalidScheduleError as error:
            code = "intervalle_trop_court" if "minimal" in str(error) else "rythme_invalide"
            raise RoutineError(code, str(error)) from error
        if routine_schedule.minimum_gap(schedule) < timedelta(minutes=settings.min_interval_minutes):
            raise RoutineError(
                "intervalle_trop_court", f"L'intervalle minimal est de {settings.min_interval_minutes} minutes."
            )
        return schedule

    async def _valid_scope(
        self,
        user: RequestContext,
        collection_ids: list[uuid.UUID],
        assistant_id: uuid.UUID | None,
        condition: RoutineCondition,
        question: str,
    ) -> None:
        """What a routine is about must be readable by the person now. It is checked again at each run."""
        if condition == RoutineCondition.ONLY_IF_NEW and not collection_ids and assistant_id is None:
            raise RoutineError(
                "portee_requise", "Pour « seulement s'il y a du nouveau », choisissez des collections ou un assistant."
            )
        if collection_ids:
            readable = await self.collections.filter_accessible_ids(
                list(dict.fromkeys(collection_ids)), user.user_id, user.groups
            )
            if any(collection_id not in readable for collection_id in collection_ids):
                raise RoutineError(
                    "collection_inaccessible", "Une des collections n'existe pas ou ne vous est pas accessible."
                )
        if assistant_id is not None:
            try:
                await AssistantService(self.db).resolve(user, assistant_id, question)
            except (AssistantNotFoundError, NoReadableCollectionError) as error:
                raise RoutineError(
                    "assistant_inaccessible", "Cet assistant n'existe pas ou ne vous est pas accessible."
                ) from error


class RoutineAdminService:
    """What an administrator sees and sets of the routines (#524): the limits, who runs what and how much, and a way to
    put a routine aside. Never the question of a routine, nor what its conversations say."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.routines = RoutineRepository(db)

    async def settings(self) -> RoutineSettings:
        settings = await self.routines.settings()
        await self.db.commit()
        return settings

    async def update_settings(self, changes: dict) -> RoutineSettings:
        settings = await self.routines.settings()
        for field, value in changes.items():
            setattr(settings, field, value)
        await self.db.commit()
        await self.db.refresh(settings)
        return settings

    async def everyone(self, pagination: PaginationParams) -> tuple[list[tuple[Routine, RoutineRun | None]], int]:
        rows, total = await self.routines.list_all(pagination.limit, pagination.offset)
        last = await self.routines.last_runs([row.id for row in rows])
        return [(row, last.get(row.id)) for row in rows], total

    async def suspend(self, routine_id: uuid.UUID) -> Routine:
        routine = await self.routines.get(routine_id)
        if routine is None:
            raise RoutineNotFoundError(str(routine_id))
        if routine.state != RoutineState.SUSPENDED or routine.suspended_reason != "admin":
            await suspend(self.db, routine, "admin")
            await self.db.commit()
        return routine

    async def release(self, routine_id: uuid.UUID) -> Routine:
        """Lifts the suspension of an administrator: the routine goes back to paused, and its owner resumes it."""
        routine = await self.routines.get(routine_id)
        if routine is None:
            raise RoutineNotFoundError(str(routine_id))
        if routine.state == RoutineState.SUSPENDED and routine.suspended_reason == "admin":
            routine.state = RoutineState.PAUSED
            routine.suspended_reason = None
            await self.db.commit()
        return routine
