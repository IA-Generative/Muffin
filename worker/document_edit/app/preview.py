"""ODT -> PDF with LibreOffice, for the preview the user validates a draft from (#169)."""

import subprocess
import tempfile
from pathlib import Path

from app.config import settings


class PreviewError(Exception):
    """The conversion failed or produced nothing."""


def convert_to_pdf(odt: bytes) -> bytes:
    """Each conversion runs with its own LibreOffice profile: two soffice processes sharing one
    profile directory block each other (the second one hands its work to the first and exits),
    which is exactly what concurrent jobs would do. `HOME`/the profile live under a temporary
    directory because the image's root filesystem is read-only."""
    with tempfile.TemporaryDirectory(prefix="edit-preview-") as work:
        directory = Path(work)
        source = directory / "draft.odt"
        source.write_bytes(odt)
        try:
            completed = subprocess.run(
                [
                    settings.SOFFICE_BIN,
                    f"-env:UserInstallation=file://{directory / 'profile'}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(directory),
                    str(source),
                ],
                capture_output=True,
                timeout=settings.PREVIEW_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise PreviewError(f"la conversion en PDF a dépassé {settings.PREVIEW_TIMEOUT_SECONDS} secondes") from error
        except FileNotFoundError as error:
            raise PreviewError(f"LibreOffice introuvable ({settings.SOFFICE_BIN})") from error
        pdf = directory / "draft.pdf"
        if completed.returncode != 0 or not pdf.exists():
            detail = completed.stderr.decode(errors="replace").strip()[:300]
            raise PreviewError(f"la conversion en PDF a échoué{f' : {detail}' if detail else ''}")
        return pdf.read_bytes()
