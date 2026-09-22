import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.models.report import Report, ReportStatus, ReportType
from app.schemas.report import ReportAdminOut, ReportUpdate
from app.services.report_service import NotAdminError, ReportNotFoundError, ReportService

router = APIRouter(prefix="/admin/reports", tags=["Admin"])


def get_report_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ReportService:
    return ReportService(db)


ServiceDep = Annotated[ReportService, Depends(get_report_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _report_admin_out(report: Report, service: ReportService) -> ReportAdminOut:
    return ReportAdminOut(
        id=report.id,
        type=report.type,
        title=report.title,
        description=report.description,
        status=report.status,
        screenshot_url=service.screenshot_url(report),
        admin_response=report.admin_response,
        created_at=report.created_at,
        updated_at=report.updated_at,
        user_display=report.user_display,
        responded_by=report.responded_by,
    )


@router.get("", summary="Tous les signalements, filtrables par statut/type")
async def list_reports(
    user: UserDep,
    service: ServiceDep,
    status_filter: ReportStatus | None = None,
    type_filter: ReportType | None = None,
) -> list[ReportAdminOut]:
    try:
        reports = await service.list_all_reports(user, status_filter, type_filter)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return [_report_admin_out(report, service) for report in reports]


@router.patch("/{report_id}", summary="Changer le statut d'un signalement et/ou y répondre")
async def update_report(
    report_id: uuid.UUID, update: ReportUpdate, user: UserDep, service: ServiceDep
) -> ReportAdminOut:
    try:
        report = await service.update_report(user, report_id, update.status, update.admin_response)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    except ReportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from error
    return _report_admin_out(report, service)
