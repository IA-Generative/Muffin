from unittest.mock import MagicMock

import fakeredis
import pytest

from app.core.security.session import SessionStore


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_keycloak_openid():
    return MagicMock()


@pytest.fixture
def session_store(fake_redis, mock_keycloak_openid):
    return SessionStore(redis_client=fake_redis, keycloak_openid=mock_keycloak_openid, ttl_seconds=3600)
