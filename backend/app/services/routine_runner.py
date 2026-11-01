"""The runs of the routines (#524), started and followed by the backend itself.

A sweep every minute takes the routines that are due - locked with `SKIP LOCKED`, so that several replicas never run
the same date - moves each one to its next date, and starts a run of the agent for it, in the name of the person, with
their rights as they are now. Nothing here reads a token of the person: they are not there. What follows a run is a
task of this process: it waits for the agent to end (or for the time allowed), then writes the history, counts the
failures, and rings the bell.

What an administrator bounds is checked at each run, not only when the routine is made: the function being on, the
number of runs of the person in the day, the number of runs at the same time in the whole application."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import agent_runner
from app.core import routine_schedule
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.routine import (
    Routine,
    RoutineCondition,
    RoutineNotify,
    RoutineResultMode,
    RoutineRun,
    RoutineRunStatus,
    RoutineSettings,
    RoutineState,
)
from app.models.run import Run, RunStatus
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.routine_repository import RoutineRepository
from app.schemas.run import RunCreate
from app.services.assistant_service import AssistantNotFoundError, AssistantService, NoReadableCollectionError
from app.services.notification_service import (
    ROUTINE_COMPLETED,
    ROUTINE_FAILED,
    ROUTINE_SUSPENDED,
    NotificationService,
)
from app.services.run_service import RunService

SWEEP_EVERY_SECONDS = 60
# Housekeeping (inactive owners, old notifications, runs nobody follows any more) is done at this pace, not every sweep.
HOUSEKEEPING_EVERY = timedelta(minutes=30)
# How often a task that follows a run looks at it.
POLL_SECONDS = 3
# A run is declared lost when it has been running this long past the time allowed: the pod that followed it is gone.
LOST_AFTER_MARGIN = timedelta(minutes=3)
# How many routines one sweep starts at most, whatever the free places: a backlog is worked through over the next ones.
CLAIM_LIMIT = 50

SKIP_NO_NEW = "no_new_documents"
SKIP_PREVIOUS_RUNNING = "previous_running"
SKIP_ACCESS_LOST = "access_lost"
SKIP_DAILY_LIMIT = "daily_limit"
SKIP_BUSY = "busy"
SKIP_FUNCTION_OFF = "function_off"

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)


def schedule_of(routine: Routine) -> routine_schedule.Schedule:
    return routine_schedule.Schedule(
        kind=routine.kind,
        timezone=routine.timezone,
        interval_minutes=routine.interval_minutes,
        time_of_day=routine.time_of_day,
        weekdays=routine.weekdays,
        day_of_month=routine.day_of_month,
    )


def _title(routine: Routine, now: datetime) -> str:
    local = now.astimezone(ZoneInfo(routine.timezone))
    return f"Routine : {routine.name} – {local:%d/%m/%Y}"[:200]


class RoutineExecutor:
    """Starts one run of one routine, and says what became of it. Used by the sweep and by "run now"."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.routines = RoutineRepository(db)

    async def context_of(self, routine: Routine) -> RequestContext:
        """The person, as a routine knows them: their id, their name, the groups of their token when they last opened
        the application, and their groups in Muffin as they are now. Never an administrator, and no token."""
        profile = await self.routines.profile(routine.owner_id)
        muffin_groups = await GroupRepository(self.db).group_ids_of(routine.owner_id)
        groups = list(dict.fromkeys([*(profile.groups if profile else []), *muffin_groups]))
        return RequestContext(
            user_id=routine.owner_id,
            email=(profile.email if profile and profile.email else ""),
            roles=["user"],
            is_admin=False,
            first_name=routine.owner_display,
            groups=groups,
        )

    async def launch(self, routine_id: uuid.UUID, trigger: str) -> RoutineRun | None:
        """One run, or the reason there is none. Returns the history row, or None when the routine is gone."""
        routine = await self.routines.get_locked(routine_id)
        if routine is None:
            return None
        settings = await self.routines.settings()
        now = datetime.now(UTC)
        skipped = await self._why_not(routine, settings, trigger, now)
        if skipped is not None:
            return await self._skip(routine, skipped, trigger, now)

        user = await self.context_of(routine)
        accessible, lost, assistant_id = await self._scope(routine, user)
        if accessible is None:
            return await self._lose_access(routine, trigger, now)
        if trigger == "schedule" and routine.condition == RoutineCondition.ONLY_IF_NEW:
            since = routine.last_checked_at
            routine.last_checked_at = now
            if since is not None and not await self._anything_new(routine, accessible, since):
                return await self._skip(routine, SKIP_NO_NEW, trigger, now)

        conversation_id = await self._conversation(routine, now)
        routine.last_run_at = now
        if trigger == "schedule":
            routine.last_checked_at = now
        # The history row is written before the run, and committed with it: from then on the routine counts as running
        # for whoever looks next, though the lock on its row is let go when the run is created.
        entry = await self.routines.add_run(
            RoutineRun(
                routine_id=routine.id,
                conversation_id=conversation_id,
                status=RoutineRunStatus.RUNNING,
                trigger=trigger,
                note=f"Pas accessible à vous : {', '.join(lost)}"[:500] if lost else None,
            )
        )
        entry_id = entry.id
        try:
            run = await RunService(self.db).create_run(
                user,
                RunCreate(
                    query=routine.question,
                    conversation_id=conversation_id,
                    collection_ids=accessible,
                    include_descendants=routine.include_descendants,
                    web_search_enabled=routine.web_search,
                    interactive=False,
                    assistant_id=assistant_id,
                ),
                automated=True,
            )
        except Exception:
            logger.exception(f"The run of the routine {routine_id} could not be started")
            await self.db.rollback()
            return await self._failed_to_start(routine_id, trigger, now)
        entry = await self.routines.get_run(entry_id)
        entry.run_id = run.id
        await self.db.commit()
        routine_scheduler.watch(entry.id, run.id, settings.run_timeout_minutes)
        return entry

    # --- the checks before a run ---

    async def _why_not(self, routine: Routine, settings: RoutineSettings, trigger: str, now: datetime) -> str | None:
        if not settings.enabled:
            return SKIP_FUNCTION_OFF
        if await self.routines.is_running(routine.id):
            return SKIP_PREVIOUS_RUNNING
        if await self.routines.count_runs_since(routine.owner_id, now - timedelta(days=1)) >= (
            settings.max_runs_per_user_per_day
        ):
            return SKIP_DAILY_LIMIT
        if await self.routines.count_running() >= settings.max_concurrent:
            return SKIP_BUSY
        return None

    async def _scope(
        self, routine: Routine, user: RequestContext
    ) -> tuple[list[uuid.UUID] | None, list[str], uuid.UUID | None]:
        """The collections to search among those the routine names that the person may read now, the names of the
        ones they may not, and the assistant (None when it is gone or no longer usable). `None` for the collections
        means nothing is left of what the routine was about."""
        assistant_id = routine.assistant_id
        if assistant_id is not None:
            try:
                assistant = await AssistantService(self.db).resolve(user, assistant_id, routine.question)
            except (AssistantNotFoundError, NoReadableCollectionError):
                return None, [], None
            return assistant.collection_ids, [], assistant_id
        wanted = [uuid.UUID(collection_id) for collection_id in routine.collection_ids]
        if not wanted:
            return [], [], None
        collections = CollectionRepository(self.db)
        readable = await collections.filter_accessible_ids(wanted, user.user_id, user.groups)
        kept = [collection_id for collection_id in wanted if collection_id in readable]
        if not kept:
            return None, [], None
        lost_ids = [collection_id for collection_id in wanted if collection_id not in readable]
        names = {c.id: c.name for c in await collections.get_by_ids(lost_ids)} if lost_ids else {}
        return kept, [names.get(collection_id, "une collection supprimée") for collection_id in lost_ids], None

    async def _anything_new(self, routine: Routine, collection_ids: list[uuid.UUID], since: datetime) -> bool:
        ids = list(collection_ids)
        if routine.include_descendants and ids:
            ids += [child for child, _parent in await CollectionHierarchyRepository(self.db).descendants_by_depth(ids)]
        if not ids and not routine.collection_ids and routine.assistant_id is None:
            return True
        return await self.routines.documents_changed_since(list(dict.fromkeys(ids)), since) > 0

    async def _conversation(self, routine: Routine, now: datetime) -> uuid.UUID:
        conversations = ConversationRepository(self.db)
        if routine.result_mode == RoutineResultMode.SINGLE_CONVERSATION and routine.conversation_id is not None:
            existing = await conversations.get(routine.conversation_id, routine.owner_id)
            if existing is not None:
                return existing.id
        conversation = await conversations.create(routine.owner_id, title=_title(routine, now))
        if routine.result_mode == RoutineResultMode.SINGLE_CONVERSATION:
            routine.conversation_id = conversation.id
        await self.db.flush()
        return conversation.id

    # --- the runs that are not made ---

    async def _skip(self, routine: Routine, reason: str, trigger: str, now: datetime) -> RoutineRun:
        entry = await self.routines.add_run(
            RoutineRun(
                routine_id=routine.id,
                status=RoutineRunStatus.SKIPPED,
                skip_reason=reason,
                trigger=trigger,
                finished_at=now,
            )
        )
        await self.db.commit()
        return entry

    async def _lose_access(self, routine: Routine, trigger: str, now: datetime) -> RoutineRun:
        """Nothing the routine is about is readable by the person any more: no run, a failure counted, and they are told
        what it is about."""
        entry = await self.routines.add_run(
            RoutineRun(
                routine_id=routine.id,
                status=RoutineRunStatus.SKIPPED,
                skip_reason=SKIP_ACCESS_LOST,
                trigger=trigger,
                finished_at=now,
                error="Les collections de cette routine ne vous sont plus accessibles.",
            )
        )
        await self.db.commit()
        await record_outcome(self.db, routine.id, entry.id, succeeded=False, reason="access_lost")
        return entry

    async def _failed_to_start(self, routine_id: uuid.UUID, trigger: str, now: datetime) -> RoutineRun:
        entry = await self.routines.add_run(
            RoutineRun(
                routine_id=routine_id,
                status=RoutineRunStatus.FAILED,
                trigger=trigger,
                finished_at=now,
                error="La routine n'a pas pu démarrer.",
            )
        )
        await self.db.commit()
        await record_outcome(self.db, routine_id, entry.id, succeeded=False, reason="start")
        return entry


async def record_outcome(
    db: AsyncSession, routine_id: uuid.UUID, routine_run_id: uuid.UUID, *, succeeded: bool, reason: str = ""
) -> None:
    """What follows a run that ended: the failures in a row (and the suspension past the limit), and the bell.
    A notification holds the name of the routine and a link - never what the answer says."""
    repository = RoutineRepository(db)
    routine = await repository.get_locked(routine_id)
    entry = await repository.get_run(routine_run_id)
    if routine is None or entry is None:
        return
    settings = await repository.settings()
    notifications = NotificationService(db)
    if succeeded:
        routine.consecutive_failures = 0
        if routine.notify == RoutineNotify.ALWAYS:
            summary = "Le résultat est prêt." + (f" {entry.note}." if entry.note else "")
            link = f"/c/{entry.conversation_id}" if entry.conversation_id else "/routines"
            await notifications.notify(
                routine.owner_id,
                ROUTINE_COMPLETED,
                f"Routine « {routine.name} » terminée",
                summary,
                link,
                {"routine_id": str(routine.id), "conversation_id": str(entry.conversation_id or "")},
            )
    else:
        routine.consecutive_failures += 1
        if routine.notify != RoutineNotify.NEVER:
            await notifications.notify(
                routine.owner_id,
                ROUTINE_FAILED,
                f"Routine « {routine.name} » en échec",
                entry.error or "L'exécution n'a pas abouti.",
                "/routines",
                {"routine_id": str(routine.id), "reason": reason},
            )
        if routine.state == RoutineState.ACTIVE and routine.consecutive_failures >= settings.max_consecutive_failures:
            await suspend(db, routine, "failures")
    await db.commit()


async def suspend(db: AsyncSession, routine: Routine, reason: str) -> None:
    """Puts a routine aside - by the system (`failures`, `inactive`) or an administrator (`admin`) - and tells its
    owner. The caller commits."""
    routine.state = RoutineState.SUSPENDED
    routine.suspended_reason = reason
    routine.next_run_at = None
    why = {
        "failures": "elle a échoué plusieurs fois de suite",
        "inactive": "vous ne vous êtes pas connecté depuis longtemps",
        "admin": "un administrateur l'a suspendue",
    }.get(reason, "elle a été suspendue")
    await NotificationService(db).notify(
        routine.owner_id,
        ROUTINE_SUSPENDED,
        f"Routine « {routine.name} » suspendue",
        f"Parce que {why}. Vous pouvez la reprendre depuis la page Routines.",
        "/routines",
        {"routine_id": str(routine.id), "reason": reason},
    )


class RoutineScheduler:
    def __init__(self) -> None:
        self._sweeper: asyncio.Task | None = None
        self._watchers: dict[uuid.UUID, asyncio.Task] = {}
        self._last_housekeeping: datetime | None = None

    async def start_up(self) -> None:
        self._sweeper = asyncio.create_task(self._loop(), name="routine-sweeper")

    async def shut_down(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
        for task in list(self._watchers.values()):
            task.cancel()
        await asyncio.gather(*self._watchers.values(), return_exceptions=True)

    def watch(self, routine_run_id: uuid.UUID, run_id: uuid.UUID, timeout_minutes: int) -> None:
        """Follows the run of the agent until it ends or the time allowed is over."""
        task = asyncio.create_task(self._follow(routine_run_id, run_id, timeout_minutes), name=f"routine-{run_id}")
        self._watchers[routine_run_id] = task
        task.add_done_callback(lambda _task: self._watchers.pop(routine_run_id, None))

    def is_following(self, routine_run_id: uuid.UUID) -> bool:
        return routine_run_id in self._watchers

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_SECONDS)
            try:
                await self.sweep()
            except Exception:
                logger.exception("The sweep of the routines failed")

    async def sweep(self, now: datetime | None = None) -> int:
        """One sweep: what is lost is closed, what is due is started. Returns how many routines were started."""
        now = now or datetime.now(UTC)
        async with async_session_factory() as db:
            settings = await RoutineRepository(db).settings()
            await db.commit()
        await self.housekeeping(now)
        if not settings.enabled:
            return 0
        started = 0
        for routine_id in await self._claim(now, settings):
            async with async_session_factory() as db:
                try:
                    entry = await RoutineExecutor(db).launch(routine_id, "schedule")
                except Exception:
                    logger.exception(f"The routine {routine_id} could not be run")
                    continue
            started += int(entry is not None and entry.status == RoutineRunStatus.RUNNING)
        return started

    async def _claim(self, now: datetime, settings: RoutineSettings) -> list[uuid.UUID]:
        """The routines to run now, each moved to its next date in the same transaction as it is taken. As many as there
        are places left for runs at the same time."""
        async with async_session_factory() as db:
            repository = RoutineRepository(db)
            free = settings.max_concurrent - await repository.count_running()
            if free <= 0:
                return []
            due = await repository.claim_due(now, min(free, CLAIM_LIMIT))
            for routine in due:
                try:
                    routine.next_run_at = routine_schedule.advance(
                        schedule_of(routine), routine.next_run_at or now, now
                    )
                except routine_schedule.InvalidScheduleError:
                    logger.exception(f"The rhythm of the routine {routine.id} cannot be computed")
                    routine.next_run_at = now + timedelta(days=1)
            ids = [routine.id for routine in due]
            await db.commit()
        return ids

    async def housekeeping(self, now: datetime, *, force: bool = False) -> None:
        if not force and self._last_housekeeping is not None and now - self._last_housekeeping < HOUSEKEEPING_EVERY:
            return
        self._last_housekeeping = now
        try:
            async with async_session_factory() as db:
                settings = await RoutineRepository(db).settings()
                await self._close_lost_runs(db, settings, now)
                await self._suspend_inactive(db, settings, now)
                await NotificationService(db).purge()
        except Exception:
            logger.exception("The housekeeping of the routines failed")

    async def _close_lost_runs(self, db: AsyncSession, settings: RoutineSettings, now: datetime) -> None:
        """A run nobody follows any more - its pod went down - fails, so that the routine is not stuck "running"."""
        repository = RoutineRepository(db)
        limit = now - timedelta(minutes=settings.run_timeout_minutes) - LOST_AFTER_MARGIN
        for entry in await repository.stale_runs(limit):
            if self.is_following(entry.id):
                continue
            entry.status = RoutineRunStatus.FAILED
            entry.finished_at = now
            entry.error = "L'exécution a été interrompue."
            await db.commit()
            await record_outcome(db, entry.routine_id, entry.id, succeeded=False, reason="lost")

    @staticmethod
    async def _suspend_inactive(db: AsyncSession, settings: RoutineSettings, now: datetime) -> None:
        repository = RoutineRepository(db)
        for routine in await repository.inactive_active(now - timedelta(days=settings.inactive_days)):
            await suspend(db, routine, "inactive")
        await db.commit()

    async def _follow(self, routine_run_id: uuid.UUID, run_id: uuid.UUID, timeout_minutes: int) -> None:
        deadline = datetime.now(UTC) + timedelta(minutes=timeout_minutes)
        status: RunStatus | None = None
        try:
            while datetime.now(UTC) < deadline:
                await asyncio.sleep(POLL_SECONDS)
                async with async_session_factory() as db:
                    run = await db.get(Run, run_id)
                    status = run.status if run is not None else RunStatus.FAILED
                if status in _TERMINAL:
                    break
            else:
                await self._stop(run_id)
                status = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"Following the run {run_id} of a routine failed")
            status = RunStatus.FAILED
        await self._conclude(routine_run_id, run_id, status)

    @staticmethod
    async def _stop(run_id: uuid.UUID) -> None:
        """The time allowed is over: the agent is stopped and the run marked as failed."""
        agent_runner.cancel(str(run_id))
        async with async_session_factory() as db:
            run = await db.get(Run, run_id)
            if run is not None and run.status not in _TERMINAL:
                run.status = RunStatus.FAILED
                run.error = "Délai dépassé."
                await db.commit()

    @staticmethod
    async def _conclude(routine_run_id: uuid.UUID, run_id: uuid.UUID, status: RunStatus | None) -> None:
        async with async_session_factory() as db:
            repository = RoutineRepository(db)
            entry = await repository.get_run(routine_run_id)
            if entry is None or entry.status != RoutineRunStatus.RUNNING:
                return
            succeeded = status == RunStatus.COMPLETED
            entry.status = RoutineRunStatus.SUCCEEDED if succeeded else RoutineRunStatus.FAILED
            entry.finished_at = datetime.now(UTC)
            entry.total_tokens = int(await repository.tokens_of(run_id))
            if not succeeded:
                entry.error = (
                    "Le délai est dépassé." if status is None else "L'agent n'a pas pu répondre à la question."
                )
            await db.commit()
            await record_outcome(
                db,
                entry.routine_id,
                routine_run_id,
                succeeded=succeeded,
                reason="timeout" if status is None else "failed",
            )


routine_scheduler = RoutineScheduler()
