"""The call to the SQL worker (#432): a Celery task sent by name to its queue, whose state is polled.

It does not block on the result: between two looks it asks whether the run was cancelled (#326), as the extraction
worker
does with the OCR pods - and it revokes what it sent when it is. A worker that does not answer in time
is an error with a clear message, not a task that hangs."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.agent.cancellation import RunCancelled, raise_if_cancelled
from app.agent.config import settings

RUN_QUERY_TASK = "app.tasks.run_query"
RENDER_CHART_TASK = "app.tasks.render_chart"


class SqlWorkerUnavailable(Exception):
    """The SQL worker did not answer, or answered something that is not its contract."""


async def run_remote_query(
    payload: dict[str, Any],
    app: Any = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    """The worker's answer - a QueryResult or a QueryFailure in JSON - for this QueryRequest."""
    return await _call(RUN_QUERY_TASK, payload, settings.TABULAR_QUERY_TIMEOUT_SECONDS, app, clock, sleep)


async def render_remote_chart(
    payload: dict[str, Any],
    app: Any = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    """The worker's answer - a ChartResult (the PNG) or a ChartFailure in JSON - for this ChartRequest."""
    return await _call(RENDER_CHART_TASK, payload, settings.TABULAR_CHART_TIMEOUT_SECONDS, app, clock, sleep)


async def _call(
    task: str,
    payload: dict[str, Any],
    timeout: float,
    app: Any,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> dict[str, Any]:
    # Celery's client is synchronous (a round trip to Redis each time): its calls go to a thread, so that the loop that
    # runs every run never waits on them.
    if app is None:
        from app.core.tasks import _celery_app as app
    try:
        result = await asyncio.to_thread(app.send_task, task, args=[payload], queue=settings.SQL_QUEUE_NAME)
    except Exception as error:
        raise SqlWorkerUnavailable(f"Le worker de requêtes est injoignable ({type(error).__name__}).") from error
    deadline = clock() + timeout
    try:
        while not await asyncio.to_thread(result.ready):
            raise_if_cancelled()
            if clock() > deadline:
                await asyncio.to_thread(result.revoke)
                raise SqlWorkerUnavailable(f"Le worker de requêtes n'a pas répondu en {timeout:g} secondes.")
            await sleep(settings.TABULAR_POLL_SECONDS)
        if not await asyncio.to_thread(result.successful):
            logger.warning(f"The SQL worker's task failed: {result.result!r}")
            raise SqlWorkerUnavailable("Le worker de requêtes a échoué sans répondre.")
        answer = result.result
    except (RunCancelled, asyncio.CancelledError):
        # What was sent is no longer wanted.
        try:
            if not result.ready():
                result.revoke()
        except Exception as error:
            logger.debug(f"Could not revoke the SQL task: {error}")
        raise
    finally:
        try:
            result.forget()
        except Exception as error:
            logger.debug(f"Could not forget the SQL task's result: {error}")
    if not isinstance(answer, dict) or answer.get("status") not in ("completed", "failed"):
        raise SqlWorkerUnavailable("Le worker de requêtes a répondu autre chose que son contrat.")
    return answer
