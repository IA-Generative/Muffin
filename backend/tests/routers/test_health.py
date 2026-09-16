from unittest.mock import patch

from app.schemas.health import Health


def test_health_is_healthy_when_redis_is_up(client):
    with patch("app.routers.health.redis_connector") as mock_connector:
        mock_connector.get_health.return_value = Health(name="redis", status="healthy")

        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["dependencies"] == [{"name": "redis", "status": "healthy", "extras": None}]


def test_health_is_unhealthy_when_a_dependency_is_down(client):
    with patch("app.routers.health.redis_connector") as mock_connector:
        mock_connector.get_health.return_value = Health(
            name="redis", status="unhealthy", extras={"error": "connection refused"}
        )

        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
