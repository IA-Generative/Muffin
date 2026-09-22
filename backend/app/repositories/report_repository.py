import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report, ReportStatus, ReportType


class ReportRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: str,
        user_display: str,
        type_: ReportType,
        title: str,
        description: str,
        screenshot_key: str | None,
    ) -> Report:
        report = Report(
            user_id=user_id,
            user_display=user_display,
            type=type_,
            title=title,
            description=description,
            screenshot_key=screenshot_key,
        )
        self.db.add(report)
        await self.db.flush()
        return report

    async def get(self, report_id: uuid.UUID) -> Report | None:
        result = await self.db.execute(select(Report).where(Report.id == report_id))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> list[Report]:
        result = await self.db.execute(
            select(Report).where(Report.user_id == user_id).order_by(Report.created_at.desc())
        )
        return list(result.scalars())

    async def list_all(self, status: ReportStatus | None = None, type_: ReportType | None = None) -> list[Report]:
        query = select(Report)
        if status is not None:
            query = query.where(Report.status == status)
        if type_ is not None:
            query = query.where(Report.type == type_)
        result = await self.db.execute(query.order_by(Report.created_at.desc()))
        return list(result.scalars())

    async def update_status_and_response(
        self,
        report: Report,
        status: ReportStatus,
        admin_response: str | None,
        responded_by: str | None,
    ) -> Report:
        report.status = status
        if admin_response is not None:
            report.admin_response = admin_response
            report.responded_by = responded_by
        await self.db.flush()
        return report
