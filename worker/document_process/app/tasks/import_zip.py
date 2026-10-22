"""Import d'une archive ZIP en collection et sous-collections (#223).

``import_zip`` : le backend a déjà créé la collection racine et stocké l'archive dans RustFS ;
cette tâche lit l'archive (règles de sécurité dans ``app/zip_import.py``), crée une
sous-collection par dossier et un document par fichier via l'API interne, puis rend compte.
Chaque document suit ensuite le pipeline habituel (``process_document``), mis en file par le
backend à son enregistrement.
"""

import hashlib
import mimetypes
import tempfile
import uuid
import zipfile

from celery.exceptions import SoftTimeLimitExceeded
from loguru import logger

from app.celery_app import celery_app
from app.config import settings
from app.tasks import _shared
from app.zip_import import (
    ArchiveRejectedError,
    MemberSkippedError,
    ZipLimits,
    count_entries,
    extract_member,
    plan_import,
)

# A member is copied into memory up to this size, then into an anonymous temporary file: small
# documents never touch the disk, a large one never fills the memory.
_SPOOL_IN_MEMORY_BYTES = 8 * 1024 * 1024
# Entries (files and folders) an archive may announce before its directory is even read, with a file
# limit set. Generous: plan_import's own file limit is what applies to a real archive; this only stops
# one claiming millions of entries from being loaded into memory to be counted.
_MAX_ENTRIES_PER_FILE_ALLOWED = 10


class _HashingSink:
    """Writes to a file and hashes what it writes: the hash of a member (#300) is known as soon as it
    has been read, without reading it again."""

    def __init__(self, sink) -> None:
        self._sink = sink
        self.hasher = hashlib.sha256()

    def write(self, data: bytes) -> None:
        self.hasher.update(data)
        self._sink.write(data)


def _limits() -> ZipLimits:
    return ZipLimits(
        max_files=settings.ZIP_IMPORT_MAX_FILES,
        max_total_bytes=settings.ZIP_IMPORT_MAX_TOTAL_BYTES,
        max_file_bytes=settings.ZIP_IMPORT_MAX_FILE_BYTES,
        max_ratio=settings.ZIP_IMPORT_MAX_RATIO,
        max_depth=settings.ZIP_IMPORT_MAX_DEPTH,
    )


def _cap(info: zipfile.ZipInfo, limits: ZipLimits, budget: int | None) -> int:
    """The most a member may expand to: its file limit and what is left of the total, or - with neither
    set - the size it declares (which zipfile never reads past anyway)."""
    return min((cap for cap in (limits.max_file_bytes, budget) if cap is not None), default=info.file_size)


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
    # counted again here, against the same overall budget (when there is one).
    budget = limits.max_total_bytes
    for planned in plan.files:
        path = "/".join((*planned.folder, planned.name))
        collection_id = collection_ids[planned.folder]
        # Same layout as a plain upload (backend's document_storage_key) - checked backend-side.
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{planned.name}"
        content_type = mimetypes.guess_type(planned.name)[0] or "application/octet-stream"
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY_BYTES) as spool:
            sink = _HashingSink(spool)
            try:
                size = extract_member(archive, planned.info, _cap(planned.info, limits, budget), sink)
            except MemberSkippedError as error:
                # Nothing stored yet: a member is only uploaded once it has been read whole, within its cap.
                summary["skipped"].append({"path": path, "reason": str(error)})
                continue
            if budget is not None:
                budget -= size
            content_hash = sink.hasher.hexdigest()
            # Already in the collection, from an earlier import or earlier in this archive (#300): it is
            # neither stored nor processed again.
            if _shared.backend_client.is_imported_duplicate(import_id, collection_id, content_hash):
                summary["skipped"].append({"path": path, "reason": "déjà présent dans la collection (doublon)"})
                continue
            spool.seek(0)
            _shared.storage.upload_fileobj(storage_key, spool, content_type=content_type)
        _shared.backend_client.add_imported_document(import_id, collection_id, planned.name, storage_key, content_hash)
        summary["documents_created"] += 1


@celery_app.task(name="app.tasks.import_zip", bind=True, soft_time_limit=settings.IMPORT_SOFT_TIME_LIMIT_SECONDS)
def import_zip(self, import_id: str) -> None:
    """Never leaves the import pending: whatever happens, the backend is told how it ended. What
    was created before a failure is kept, and the summary says so. A large archive may take a while
    and is not killed for it: only past IMPORT_SOFT_TIME_LIMIT_SECONDS does it stop, as failed."""
    collection_import = _shared.backend_client.begin_collection_import(import_id)
    summary: dict = {"collections_created": 0, "documents_created": 0, "skipped": []}
    try:
        with tempfile.TemporaryFile() as archive_file:
            _shared.storage.download_fileobj(collection_import["archive_key"], archive_file)
            entries = count_entries(archive_file)
            max_files = settings.ZIP_IMPORT_MAX_FILES
            if max_files is not None and entries is not None and entries > max_files * _MAX_ENTRIES_PER_FILE_ALLOWED:
                raise ArchiveRejectedError(f"L'archive annonce {entries} entrées, bien au-delà de ce qui est accepté.")
            with zipfile.ZipFile(archive_file) as archive:
                _run_import(import_id, collection_import["root_collection_id"], archive, summary)
    except ArchiveRejectedError as error:
        logger.warning(f"ZIP import {import_id} refused: {error}")
        _shared.backend_client.finish_collection_import(import_id, "failed", summary, str(error))
        return
    except SoftTimeLimitExceeded:
        hours = settings.IMPORT_SOFT_TIME_LIMIT_SECONDS / 3600
        logger.warning(f"ZIP import {import_id} stopped after {hours:g} h")
        _shared.backend_client.finish_collection_import(
            import_id,
            "failed",
            summary,
            f"L'import a dépassé le délai de {hours:g} h et a été interrompu : "
            f"{summary['documents_created']} document(s) déjà importé(s) ont été conservés.",
        )
        raise
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
