import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import evaluation_artifacts


@pytest.fixture(autouse=True)
def _clear_artifact_cache():
    # Tests reuse one artifact key with different content; the production cache is keyed by
    # the (unique per run) RustFS key, so it must not leak between tests.
    evaluation_artifacts.clear_cache()
    yield
    evaluation_artifacts.clear_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
