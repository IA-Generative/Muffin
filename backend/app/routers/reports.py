import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.models.report import Report, ReportType
from app.schemas.report import ReportOut
from app.services.report_service import NotReportOwnerError, ReportNotFoundError, ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])


def get_report_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ReportService:
    return ReportService(db)


ServiceDep = Annotated[ReportService, Depends(get_report_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _report_out(report: Report, service: ReportService) -> ReportOut:
    return ReportOut(
        id=report.id,
        type=report.type,
        title=report.title,
        description=report.description,
        status=report.status,
        screenshot_url=service.screenshot_url(report),
        admin_response=report.admin_response,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "",
    summary="Signaler un bug, une idée ou une question (§148)",
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    user: UserDep,
    service: ServiceDep,
    type: Annotated[ReportType, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    screenshot: UploadFile | None = None,
) -> ReportOut:
    screenshot_bytes = await screenshot.read() if screenshot is not None else None
    report = await service.create_report(
        user,
        type,
        title,
        description,
        screenshot_bytes,
        screenshot.content_type if screenshot is not None else None,
    )
    return _report_out(report, service)


@router.get("", summary="Mes signalements, les plus récents d'abord")
async def list_my_reports(user: UserDep, service: ServiceDep) -> list[ReportOut]:
    reports = await service.list_my_reports(user)
    return [_report_out(report, service) for report in reports]


@router.get("/{report_id}", summary="Un signalement, si c'est le sien (ou en tant qu'admin)")
async def get_report(report_id: uuid.UUID, user: UserDep, service: ServiceDep) -> ReportOut:
    try:
        report = await service.get_my_report(user, report_id)
    except ReportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from error
    except NotReportOwnerError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your report") from error
    return _report_out(report, service)
