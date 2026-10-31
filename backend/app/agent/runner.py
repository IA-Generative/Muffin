"""The runs of the agent, started and followed by the backend itself.

A run is a task of the backend's event loop that hands its work to a thread (the graph is made of synchronous
nodes, which
must never block the loop that serves the users). It outlives the request that created it: the user polls the run
and its
events, as before. What changed is where it runs - in the backend, with the user's access token at hand for the
tools that
need it (see user_token.py) - and what that costs:

- a run does not survive the restart of the pod that runs it. A run that stopped progressing is marked failed
(`fail_stale`),
  so the user is told rather than left waiting;
- the number of runs in progress in a pod is bounded (`AGENT_MAX_CONCURRENT_RUNS`): the others wait their turn,
queued."""

import asyncio
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import update

from app.agent.cancellation import RunCancelled, forget, mark_cancelled
from app.agent.config import settings
from app.agent.execution_metrics import measured_run
from app.agent.runtime import bind_loop
from app.agent.service import agent_service
from app.agent.usage_context import start_run
from app.agent.user_token import set_user_token
from app.db import async_session_factory
from app.models.run import Run, RunStatus

# A run that has been running or waiting for this long without a node ending is dead: every node reports its progress.
STALE_AFTER = timedelta(minutes=10)
SWEEP_EVERY_SECONDS = 300


class AgentRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._slots: asyncio.Semaphore | None = None
        self._sweeper: asyncio.Task | None = None
        self._lock = threading.Lock()

    async def start_up(self) -> None:
        """Called when the backend starts: fails what a previous pod left behind, and keeps looking for such runs."""
        loop = asyncio.get_running_loop()
        bind_loop(loop)
        self._executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_RUNS, thread_name_prefix="agent-run")
        self._slots = asyncio.Semaphore(settings.MAX_CONCURRENT_RUNS)
        await self.fail_stale()
        self._sweeper = asyncio.create_task(self._sweep(), name="agent-sweeper")

    async def shut_down(self) -> None:
        """Called when the backend stops: the runs still going are asked to stop at their next node and marked
        failed."""
        if self._sweeper is not None:
            self._sweeper.cancel()
        for run_id in list(self._tasks):
            mark_cancelled(run_id)
        for run_id, task in list(self._tasks.items()):
            task.cancel()
            await self._fail(run_id, "Le serveur a été arrêté pendant la recherche.")
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def start(self, run_id: str, user_token: str | None = None, *, resume_answer: str | None = None) -> None:
        """Starts a run in the background and returns at once. `user_token` is the user's own access token, kept in
        memory
        for this run only."""
        bind_loop(asyncio.get_running_loop())
        if self._executor is None:
            # Not started by the application's lifespan (tests, scripts): one slot at a time is the safe default.
            self._executor = ThreadPoolExecutor(
                max_workers=settings.MAX_CONCURRENT_RUNS, thread_name_prefix="agent-run"
            )
            self._slots = asyncio.Semaphore(settings.MAX_CONCURRENT_RUNS)
        task = asyncio.create_task(self._run(run_id, user_token, resume_answer), name=f"agent-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run_id, None))

    def cancel(self, run_id: str) -> None:
        """The pod that runs it stops at the next look (a wait for the SQL worker); every pod's nodes see the flag the
        backend set on the run."""
        mark_cancelled(run_id)

    def is_running(self, run_id: str) -> bool:
        return run_id in self._tasks

    async def _run(self, run_id: str, user_token: str | None, resume_answer: str | None) -> None:
        loop = asyncio.get_running_loop()
        try:
            async with self._slots:
                context = contextvars.copy_context()
                await loop.run_in_executor(
                    self._executor, context.run, self._execute, run_id, user_token, resume_answer
                )
        except asyncio.CancelledError:
            raise
        except RunCancelled:
            logger.info(f"Run {run_id} was cancelled while it waited")
        except Exception:
            # AgentService already recorded the failure on the run; this is only the trace.
            logger.exception(f"Run {run_id} failed")
        finally:
            forget(run_id)

    @staticmethod
    def _execute(run_id: str, user_token: str | None, resume_answer: str | None) -> None:
        """In the thread of the run: its context (who it is for, and their token), then the graph."""
        start_run(run_id)
        set_user_token(user_token)
        with measured_run():
            if resume_answer is None:
                agent_service.run(run_id)
            else:
                agent_service.resume(run_id, resume_answer)

    async def fail_stale(self) -> int:
        """Marks failed the runs that stopped progressing - what a pod that went down left behind."""
        limit = datetime.now(UTC) - STALE_AFTER
        async with async_session_factory() as db:
            result = await db.execute(
                update(Run)
                .where(Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)), Run.updated_at < limit)
                .values(
                    status=RunStatus.FAILED,
                    error="La recherche a été interrompue : le serveur qui l'exécutait s'est arrêté.",
                )
            )
            await db.commit()
        if result.rowcount:
            logger.warning(f"{result.rowcount} run(s) that stopped progressing marked failed")
        return result.rowcount

    async def _fail(self, run_id: str, error: str) -> None:
        try:
            async with async_session_factory() as db:
                await db.execute(
                    update(Run)
                    .where(Run.id == run_id, Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)))
                    .values(status=RunStatus.FAILED, error=error)
                )
                await db.commit()
        except Exception:
            logger.exception(f"Could not mark run {run_id} failed")

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_SECONDS)
            try:
                await self.fail_stale()
            except Exception:
                logger.exception("The look for runs that stopped progressing failed")


agent_runner = AgentRunner()
