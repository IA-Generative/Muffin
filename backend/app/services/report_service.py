import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.models.report import Report, ReportStatus, ReportType
from app.repositories.report_repository import ReportRepository


class NotAdminError(Exception):
    pass


class ReportNotFoundError(Exception):
    pass


class NotReportOwnerError(Exception):
    pass


def _reporter_display(user: RequestContext) -> str:
    """ "Jean Dupont" - the full name, not the initial-style "Jean D." used elsewhere for
    documents (§122): an admin triaging reports benefits from being able to recognize/contact the
    exact reporter, this isn't shown broadly across the app like a document's uploader is."""
    full_name = f"{user.first_name} {user.last_name}".strip()
    if full_name:
        return full_name
    if user.email:
        return user.email.split("@")[0]
    return user.user_id


class ReportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = ReportRepository(db)

    async def create_report(
        self,
        user: RequestContext,
        type_: ReportType,
        title: str,
        description: str,
        screenshot: bytes | None,
        screenshot_content_type: str | None,
    ) -> Report:
        screenshot_key = None
        if screenshot is not None:
            screenshot_key = f"reports/{user.user_id}/{uuid.uuid4()}.png"
            storage.put_object(screenshot_key, screenshot, content_type=screenshot_content_type or "image/png")
        report = await self.repository.create(
            user_id=user.user_id,
            user_display=_reporter_display(user),
            type_=type_,
            title=title,
            description=description,
            screenshot_key=screenshot_key,
        )
        await self.db.commit()
        return report

    async def list_my_reports(self, user: RequestContext) -> list[Report]:
        return await self.repository.list_for_user(user.user_id)

    async def get_my_report(self, user: RequestContext, report_id: uuid.UUID) -> Report:
        report = await self.repository.get(report_id)
        if report is None:
            raise ReportNotFoundError(str(report_id))
        if report.user_id != user.user_id and not user.is_admin:
            raise NotReportOwnerError(str(report_id))
        return report

    async def list_all_reports(
        self, user: RequestContext, status: ReportStatus | None, type_: ReportType | None
    ) -> list[Report]:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        return await self.repository.list_all(status=status, type_=type_)

    async def update_report(
        self,
        user: RequestContext,
        report_id: uuid.UUID,
        status: ReportStatus,
        admin_response: str | None,
    ) -> Report:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        report = await self.repository.get(report_id)
        if report is None:
            raise ReportNotFoundError(str(report_id))
        updated = await self.repository.update_status_and_response(
            report, status, admin_response, _reporter_display(user) if admin_response is not None else None
        )
        await self.db.commit()
        # UPDATE (unlike the INSERT in create_report) can't populate onupdate=func.now() via
        # RETURNING automatically - SQLAlchemy just expires it, so it must be refreshed
        # explicitly or reading it right after commit fails outside an async context.
        await self.db.refresh(updated, attribute_names=["updated_at"])
        return updated

    def screenshot_url(self, report: Report) -> str | None:
        if report.screenshot_key is None:
            return None
        return storage.get_presigned_url(report.screenshot_key)
