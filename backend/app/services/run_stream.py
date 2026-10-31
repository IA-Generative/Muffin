"""The live stream of a run (#510): its steps, the answer as it is written, and its status, in the order they happen.

A Redis stream per run, so that whichever pod holds the request of the chat reads what the pod running the agent wrote.
It only carries what to show now: the run and its events stay in the database, which is what the chat reads when there
is no stream (expired, or Redis down) and what it reads once the run is over."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.config import RunSettings
from app.connectors import async_redis

_settings = RunSettings()

STEP = "step"
DELTA = "delta"
STATUS = "status"
PING = "ping"

# The statuses after which nothing more comes: the chat is done with the stream.
ENDING_STATUSES = frozenset({"completed", "failed", "cancelled", "waiting_for_user"})

# What publishing may take: the agent never waits long on a stream that is only there to show.
_PUBLISH_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class StreamEntry:
    id: str
    kind: str
    payload: dict[str, Any]


def stream_key(run_id: uuid.UUID | str) -> str:
    return f"run:{run_id}:stream"


async def publish(run_id: uuid.UUID | str, kind: str, payload: dict[str, Any]) -> None:
    """Best effort, like the partial answer before it: a missed entry only means the chat shows it a little later (the
    run's own state is always right), and it must never be the reason a run or a request fails."""
    key = stream_key(run_id)
    try:
        async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
            redis = async_redis()
            await redis.xadd(
                key,
                {"k": kind, "d": json.dumps(payload, default=str)},
                maxlen=_settings.RUN_STREAM_MAXLEN,
                approximate=True,
            )
            await redis.expire(key, _settings.RUN_STREAM_TTL_SECONDS)
    except Exception:
        logger.warning(f"Could not publish a {kind} entry to the stream of run {run_id}", exc_info=True)


async def read(run_id: uuid.UUID | str, after: str, block_ms: int) -> list[StreamEntry]:
    """What came after `after` ("0-0" for everything), waiting up to `block_ms` for the first entry."""
    response = await async_redis().xread({stream_key(run_id): after}, count=200, block=block_ms or None)
    entries: list[StreamEntry] = []
    for _key, items in response or []:
        for entry_id, fields in items:
            entries.append(StreamEntry(entry_id, fields["k"], json.loads(fields["d"])))
    return entries
