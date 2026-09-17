from unittest.mock import AsyncMock, patch

from app.schemas.health import Health


def test_health_is_healthy_when_all_dependencies_are_up(client):
    with (
        patch("app.routers.health.redis_connector") as mock_redis,
        patch("app.routers.health.qdrant_connector") as mock_qdrant,
        patch("app.routers.health.db_connector") as mock_db,
    ):
        mock_redis.get_health.return_value = Health(name="redis", status="healthy")
        mock_qdrant.get_health.return_value = Health(name="qdrant", status="healthy")
        mock_db.get_health = AsyncMock(return_value=Health(name="database", status="healthy"))

        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["dependencies"] == [
        {"name": "redis", "status": "healthy", "extras": None},
        {"name": "qdrant", "status": "healthy", "extras": None},
        {"name": "database", "status": "healthy", "extras": None},
    ]


def test_health_is_unhealthy_when_a_dependency_is_down(client):
    with (
        patch("app.routers.health.redis_connector") as mock_redis,
        patch("app.routers.health.qdrant_connector") as mock_qdrant,
        patch("app.routers.health.db_connector") as mock_db,
    ):
        mock_redis.get_health.return_value = Health(
            name="redis", status="unhealthy", extras={"error": "connection refused"}
        )
        mock_qdrant.get_health.return_value = Health(name="qdrant", status="healthy")
        mock_db.get_health = AsyncMock(return_value=Health(name="database", status="healthy"))

        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
