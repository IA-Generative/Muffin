import redis
import redis.asyncio as redis_async
from qdrant_client import QdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import QdrantSettings, RedisSettings
from app.db import engine as db_engine
from app.schemas.health import Health


class RedisConnector:
    def __init__(self, url: str) -> None:
        self.client = redis.Redis.from_url(url, decode_responses=True)

    def get_health(self) -> Health:
        try:
            self.client.ping()
            return Health(name="redis", status="healthy")
        except redis.RedisError as error:
            return Health(name="redis", status="unhealthy", extras={"error": str(error)})


_async_redis: redis_async.Redis | None = None


def async_redis() -> redis_async.Redis:
    """The Redis client for what must not block the event loop - the live stream of a run (#510). Built on first use, in
    the loop that uses it: an asyncio connection belongs to the loop that opened it."""
    global _async_redis
    if _async_redis is None:
        _async_redis = redis_async.Redis.from_url(redis_settings.REDIS_URL, decode_responses=True)
    return _async_redis


class QdrantConnector:
    def __init__(self, url: str, api_key: str | None) -> None:
        # The client never connects at construction time (check_compatibility would make it): failing to
        # reach Qdrant yet (e.g. it's still starting) can't crash the app on boot, only get_health() reports
        # it as down. Collections are created lazily, by app/services/vector_store.py, on first write.
        self.client = QdrantClient(url=url, api_key=api_key, check_compatibility=False)

    def get_health(self) -> Health:
        try:
            self.client.get_collections()
            return Health(name="qdrant", status="healthy")
        except Exception as error:
            return Health(name="qdrant", status="unhealthy", extras={"error": str(error)})


class DatabaseConnector:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get_health(self) -> Health:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return Health(name="database", status="healthy")
        except Exception as error:
            return Health(name="database", status="unhealthy", extras={"error": str(error)})


redis_settings = RedisSettings()
redis_connector = RedisConnector(redis_settings.REDIS_URL)
db_connector = DatabaseConnector(db_engine)
qdrant_settings = QdrantSettings()
qdrant_connector = QdrantConnector(qdrant_settings.QDRANT_URL, qdrant_settings.QDRANT_API_KEY)
