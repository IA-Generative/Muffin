import meilisearch
import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import MeilisearchSettings, RedisSettings
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


class MeilisearchConnector:
    def __init__(self, url: str, api_key: str | None) -> None:
        # The client itself never connects at construction time (it's just an HTTP wrapper) -
        # failing to reach Meilisearch yet (e.g. it's still starting) can't crash the app on
        # boot, only get_health() should ever report it as down. Enabling the vector store
        # feature (app/services/vector_store.py needs it for embedders/hybrid search) happens
        # lazily instead, right before the first index is ever created - see
        # vector_store._create_index - for the same "must not crash boot" reason.
        self.client = meilisearch.Client(url, api_key)

    def get_health(self) -> Health:
        try:
            self.client.health()
            return Health(name="meilisearch", status="healthy")
        except Exception as error:
            return Health(name="meilisearch", status="unhealthy", extras={"error": str(error)})


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
meilisearch_settings = MeilisearchSettings()
meilisearch_connector = MeilisearchConnector(meilisearch_settings.MEILI_URL, meilisearch_settings.MEILI_API_KEY)
