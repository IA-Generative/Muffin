"""Import d'une archive ZIP en collection et sous-collections (#223).

``import_zip`` : le backend a déjà créé la collection racine et stocké l'archive dans RustFS ;
cette tâche lit l'archive (règles de sécurité dans ``app/zip_import.py``), crée une
sous-collection par dossier et un document par fichier via l'API interne, puis rend compte.
Chaque document suit ensuite le pipeline habituel (``process_document``), mis en file par le
backend à son enregistrement.
"""

import mimetypes
import tempfile
import uuid
import zipfile

from loguru import logger

from app.celery_app import celery_app
from app.config import settings
from app.task_logging import capture_task_logs
from app.tasks import _shared
from app.zip_import import (
    ArchiveRejectedError,
    MemberSkippedError,
    ZipLimits,
    extract_member,
    plan_import,
)

# A member is copied into memory up to this size, then into an anonymous temporary file: small
# documents never touch the disk, a large one never fills the memory.
_SPOOL_IN_MEMORY_BYTES = 8 * 1024 * 1024


def _limits() -> ZipLimits:
    return ZipLimits(
        max_files=settings.ZIP_IMPORT_MAX_FILES,
        max_total_bytes=settings.ZIP_IMPORT_MAX_TOTAL_BYTES,
        max_file_bytes=settings.ZIP_IMPORT_MAX_FILE_BYTES,
        max_ratio=settings.ZIP_IMPORT_MAX_RATIO,
        max_depth=settings.ZIP_IMPORT_MAX_DEPTH,
    )


def _run_import(import_id: str, root_collection_id: str, archive: zipfile.ZipFile, summary: dict) -> None:
    limits = _limits()
    plan = plan_import(archive.infolist(), limits)
    summary["skipped"].extend(plan.skipped)

    collection_ids: dict[tuple[str, ...], str] = {(): root_collection_id}
    for folder in plan.folders:
        collection_ids[folder] = _shared.backend_client.create_imported_collection(
            import_id, collection_ids[folder[:-1]], folder[-1]
        )
        summary["collections_created"] += 1

    # The sizes plan_import checked are only what the archive declares - what is actually read is
    # counted again here, against the same overall budget.
    budget = limits.max_total_bytes
    for planned in plan.files:
        path = "/".join((*planned.folder, planned.name))
        collection_id = collection_ids[planned.folder]
        # Same layout as a plain upload (backend's document_storage_key) - checked backend-side.
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{planned.name}"
        content_type = mimetypes.guess_type(planned.name)[0] or "application/octet-stream"
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY_BYTES) as spool:
            try:
                size = extract_member(archive, planned.info, min(limits.max_file_bytes, budget), spool)
            except MemberSkippedError as error:
                # Nothing stored yet: a member is only uploaded once it has been read whole, within its cap.
                summary["skipped"].append({"path": path, "reason": str(error)})
                continue
            budget -= size
            spool.seek(0)
            _shared.storage.upload_fileobj(storage_key, spool, content_type=content_type)
        _shared.backend_client.add_imported_document(import_id, collection_id, planned.name, storage_key)
        summary["documents_created"] += 1


@celery_app.task(name="app.tasks.import_zip", bind=True)
def import_zip(self, import_id: str) -> None:
    """Never leaves the import pending: whatever happens, the backend is told how it ended. What
    was created before a failure is kept, and the summary says so."""
    with capture_task_logs(self.request.id):
        collection_import = _shared.backend_client.begin_collection_import(import_id)
        summary: dict = {"collections_created": 0, "documents_created": 0, "skipped": []}
        try:
            with tempfile.TemporaryFile() as archive_file:
                _shared.storage.download_fileobj(collection_import["archive_key"], archive_file)
                archive_file.seek(0)
                with zipfile.ZipFile(archive_file) as archive:
                    _run_import(import_id, collection_import["root_collection_id"], archive, summary)
        except ArchiveRejectedError as error:
            logger.warning(f"ZIP import {import_id} refused: {error}")
            _shared.backend_client.finish_collection_import(import_id, "failed", summary, str(error))
            return
        except zipfile.BadZipFile as error:
            logger.warning(f"ZIP import {import_id}: unreadable archive ({error})")
            _shared.backend_client.finish_collection_import(
                import_id, "failed", summary, "L'archive est corrompue ou n'est pas un ZIP valide."
            )
            return
        except Exception:
            logger.exception(f"ZIP import {import_id} failed")
            _shared.backend_client.finish_collection_import(
                import_id, "failed", summary, "L'import s'est interrompu sur une erreur inattendue."
            )
            raise

        logger.info(
            f"ZIP import {import_id} done: {summary['collections_created']} collection(s), "
            f"{summary['documents_created']} document(s), {len(summary['skipped'])} skipped"
        )
        _shared.backend_client.finish_collection_import(import_id, "completed", summary)
