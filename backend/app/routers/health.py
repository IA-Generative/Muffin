import datetime

from fastapi import APIRouter, Response, status

from app import __name__ as app_name
from app import __version__
from app.connectors import redis_connector
from app.logger import logger
from app.schemas.health import HealthReport

router = APIRouter(tags=["Health"])
up_time = datetime.datetime.now().isoformat()


@router.get(
    "/health",
    summary="Perform a health check",
    response_description="Health of the API and its dependencies",
    status_code=status.HTTP_200_OK,
    response_model=HealthReport,
)
async def get_health(response: Response) -> HealthReport:
    dependencies = [redis_connector.get_health()]

    api_status = "healthy"
    for dependency in dependencies:
        if dependency.status == "unhealthy":
            api_status = "unhealthy"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            logger.error(f"Health check failed for dependency '{dependency.name}': {dependency.extras}")

    return HealthReport(
        name=app_name, version=__version__, up_time=up_time, status=api_status, dependencies=dependencies
    )
