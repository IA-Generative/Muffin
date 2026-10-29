import pytest
from fastapi.testclient import TestClient

from app.core.security.factory import get_current_user, get_token_identity
from app.main import app


@pytest.fixture
def client() -> TestClient:
    # The synchronous client runs each request on a loop of its own, which the async database engine (bound to
    # another) cannot serve: the identity is the token's alone here, without the groups of the database (#453).
    app.dependency_overrides.setdefault(get_current_user, get_token_identity)
    yield TestClient(app)
    if app.dependency_overrides.get(get_current_user) is get_token_identity:
        del app.dependency_overrides[get_current_user]
