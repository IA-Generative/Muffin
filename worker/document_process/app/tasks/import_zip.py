"""Import d'une archive ZIP en collection et sous-collections (#223).

``import_zip`` : le backend a déjà créé la collection racine et stocké l'archive dans RustFS ;
cette tâche lit le répertoire de l'archive par plages d'octets (sans la télécharger entière), applique les
règles de sécurité (``app/zip_import.py``), crée une sous-collection par dossier, range le plan - quels
fichiers, dans quelles collections - à côté de l'archive, puis le découpe en lots de ``IMPORT_BATCH_FILES``
fichiers (#334). Chaque lot est lu par une tâche à elle, ``import_zip_batch``, ``IMPORT_WINDOW`` à la fois :
un lot qui se termine lance le suivant. Le lot qui complète l'import en rend compte, avec le résumé de tous.
Une petite archive (un seul lot) est lue sans quitter cette tâche.
Chaque document suit ensuite le pipeline habituel (``process_document``), mis en file par le
backend selon la fenêtre de son import (#335).
"""

import hashlib
import json
import mimetypes
import tempfile
import time
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


def _plan_key(archive_key: str) -> str:
    """Where the plan is stored: beside the archive - the backend removes it with the archive, see
    collection_import_service.plan_key."""
    return f"{archive_key}.plan.json"


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"


def _plan_and_start(import_id: str, collection_import: dict, archive: zipfile.ZipFile, summary: dict) -> dict | None:
    """Creates the collections, stores the plan and announces the batches. Returns the payload of the
    first batch when the archive is a single one (read by the caller, without a task of its own), the
    summary having been sent when there is nothing to read; None once the batches are started."""
    limits = _limits()
    infos = archive.infolist()
    plan = plan_import(infos, limits)
    summary["skipped"].extend(plan.skipped)

    collection_ids: dict[tuple[str, ...], str] = {(): collection_import["root_collection_id"]}
    for folder in plan.folders:
        collection_ids[folder] = _shared.backend_client.create_imported_collection(
            import_id, collection_ids[folder[:-1]], folder[-1]
        )
        summary["collections_created"] += 1

    positions = {id(info): position for position, info in enumerate(infos)}
    files = [
        {
            "index": positions[id(planned.info)],
            "name": planned.name,
            "path": "/".join((*planned.folder, planned.name)),
            "collection_id": collection_ids[planned.folder],
        }
        for planned in plan.files
    ]
    size = max(settings.IMPORT_BATCH_FILES, 1)
    batches = -(-len(files) // size)
    if batches == 0:
        _shared.backend_client.finish_collection_import(import_id, "completed", summary)
        logger.info(f"ZIP import {import_id} done: {summary['collections_created']} collection(s), nothing to read")
        return None
    archive_key = collection_import["archive_key"]
    _shared.storage.put_object(_plan_key(archive_key), json.dumps({"files": files}).encode(), "application/json")
    _shared.backend_client.begin_import_batches(
        import_id,
        [f"batch:{number}" for number in range(batches)],
        {"collections_created": summary["collections_created"], "skipped": summary["skipped"]},
    )
    window = max(settings.IMPORT_WINDOW, 1)
    logger.info(
        f"ZIP import {import_id}: {len(files)} file(s) in {batches} batch(es) of {size}, "
        f"{min(window, batches)} at a time"
    )
    payload = {
        "import_id": import_id,
        # The root collection: what the logs of the batches are filed under (app/task_logging.py).
        "collection_id": collection_import["root_collection_id"],
        "archive_key": archive_key,
        "size": size,
        "window": window,
        "total": batches,
        "started": time.time(),
    }
    if batches == 1:
        return {**payload, "batch": 0}
    for number in range(min(window, batches)):
        _spawn_batch(payload, number)
    return None


def _spawn_batch(payload: dict, batch: int) -> None:
    import_zip_batch.apply_async(args=[{**payload, "batch": batch}])


def _import_files(import_id: str, archive: zipfile.ZipFile, files: list[dict], limits: ZipLimits, result: dict) -> None:
    """Reads the files of the plan one after the other: each is extracted into a temporary file, hashed,
    stored and registered. `result` is what they amount to - the documents created, the files skipped.

    The size the archive may expand to is guaranteed by the plan (the sizes it declares, which zipfile never
    reads past), not counted again here as the files are read: batches run at the same time."""
    infos = archive.infolist()
    for planned in files:
        path, collection_id, name = planned["path"], planned["collection_id"], planned["name"]
        info = infos[planned["index"]]
        # Same layout as a plain upload (backend's document_storage_key) - checked backend-side.
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{name}"
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY_BYTES) as spool:
            sink = _HashingSink(spool)
            try:
                extract_member(archive, info, _cap(info, limits, limits.max_total_bytes), sink)
            except MemberSkippedError as error:
                # Nothing stored yet: a member is only uploaded once it has been read whole, within its cap.
                result["skipped"].append({"path": path, "reason": str(error)})
                continue
            content_hash = sink.hasher.hexdigest()
            # Already in the collection, from an earlier import or earlier in this archive (#300): it is
            # neither stored nor processed again.
            if _shared.backend_client.is_imported_duplicate(import_id, collection_id, content_hash):
                result["skipped"].append({"path": path, "reason": _DUPLICATE})
                continue
            spool.seek(0)
            _shared.storage.upload_fileobj(storage_key, spool, content_type=content_type)
        if (
            _shared.backend_client.add_imported_document(import_id, collection_id, name, storage_key, content_hash)
            is None
        ):
            # Another batch registered the same file between the check and now: the backend dropped ours.
            result["skipped"].append({"path": path, "reason": _DUPLICATE})
            continue
        result["documents_created"] += 1


_DUPLICATE = "déjà présent dans la collection (doublon)"


def _fail(import_id: str, error: str, summary: dict) -> None:
    _shared.backend_client.finish_collection_import(import_id, "failed", summary, error)


def _process_batch(payload: dict) -> None:
    """A batch of the plan: its files are read, the backend is told how far the import is, and the batch
    that follows in its window is started. Never leaves the import running: whatever happens, the backend
    is told how it ended, with what this batch had done - the others' is already there."""
    import_id, number = payload["import_id"], payload["batch"]
    result: dict = {"documents_created": 0, "skipped": []}
    try:
        plan = json.loads(_shared.storage.get_object(_plan_key(payload["archive_key"])))["files"]
        files = plan[number * payload["size"] : (number + 1) * payload["size"]]
        with _shared.storage.open_seekable(payload["archive_key"]) as archive_file:
            with zipfile.ZipFile(archive_file) as archive:
                _import_files(import_id, archive, files, _limits(), result)
        progress = _shared.backend_client.import_batch_done(import_id, f"batch:{number}", result)
        done, expected = progress["done"], progress["expected"]
        elapsed = time.time() - payload["started"]
        # The pace so far, so a rough estimate: a big file costs far more than a small one.
        left = f", about {_duration(elapsed / done * (expected - done))} left" if 0 < done < expected else ""
        logger.info(
            f"Imported batch {number + 1}/{payload['total']}: {done}/{expected} batch(es) done in "
            f"{_duration(elapsed)}{left}"
        )
        following = number + payload["window"]
        # An import that failed meanwhile starts nothing more.
        if progress["status"] == "running" and following < payload["total"]:
            _spawn_batch(payload, following)
        if progress["completed_now"]:
            summary = progress["summary"]
            logger.info(
                f"ZIP import {import_id} done: {summary['collections_created']} collection(s), "
                f"{summary['documents_created']} document(s), {len(summary['skipped'])} skipped"
            )
            _shared.backend_client.finish_collection_import(import_id, "completed", summary)
    except SoftTimeLimitExceeded:
        hours = settings.IMPORT_SOFT_TIME_LIMIT_SECONDS / 3600
        logger.warning(f"ZIP import {import_id} stopped after {hours:g} h")
        _fail(
            import_id,
            f"L'import a dépassé le délai de {hours:g} h et a été interrompu : "
            "les documents déjà importés ont été conservés.",
            result,
        )
        raise
    except zipfile.BadZipFile as error:
        logger.warning(f"ZIP import {import_id}: unreadable archive ({error})")
        _fail(import_id, "L'archive est corrompue ou n'est pas un ZIP valide.", result)
    except Exception:
        logger.exception(f"ZIP import {import_id} failed")
        _fail(import_id, "L'import s'est interrompu sur une erreur inattendue.", result)
        raise


@celery_app.task(name="app.tasks.import_zip", bind=True, soft_time_limit=settings.IMPORT_SOFT_TIME_LIMIT_SECONDS)
def import_zip(self, import_id: str) -> None:
    """Never leaves the import pending: whatever happens, the backend is told how it ended. What
    was created before a failure is kept, and the summary says so. A large archive may take a while
    and is not killed for it: only past IMPORT_SOFT_TIME_LIMIT_SECONDS does it stop, as failed."""
    collection_import = _shared.backend_client.begin_collection_import(import_id)
    summary: dict = {"collections_created": 0, "documents_created": 0, "skipped": []}
    single_batch = None
    try:
        # Read by ranges: the archive is not downloaded here, nor by each batch that reads a part of it.
        with _shared.storage.open_seekable(collection_import["archive_key"]) as archive_file:
            entries = count_entries(archive_file)
            max_files = settings.ZIP_IMPORT_MAX_FILES
            if max_files is not None and entries is not None and entries > max_files * _MAX_ENTRIES_PER_FILE_ALLOWED:
                raise ArchiveRejectedError(f"L'archive annonce {entries} entrées, bien au-delà de ce qui est accepté.")
            with zipfile.ZipFile(archive_file) as archive:
                single_batch = _plan_and_start(import_id, collection_import, archive, summary)
    except ArchiveRejectedError as error:
        logger.warning(f"ZIP import {import_id} refused: {error}")
        _fail(import_id, str(error), summary)
        return
    except SoftTimeLimitExceeded:
        hours = settings.IMPORT_SOFT_TIME_LIMIT_SECONDS / 3600
        logger.warning(f"ZIP import {import_id} stopped after {hours:g} h")
        _fail(
            import_id,
            f"L'import a dépassé le délai de {hours:g} h et a été interrompu : "
            f"{summary['documents_created']} document(s) déjà importé(s) ont été conservés.",
            summary,
        )
        raise
    except zipfile.BadZipFile as error:
        logger.warning(f"ZIP import {import_id}: unreadable archive ({error})")
        _fail(import_id, "L'archive est corrompue ou n'est pas un ZIP valide.", summary)
        return
    except Exception:
        logger.exception(f"ZIP import {import_id} failed")
        _fail(import_id, "L'import s'est interrompu sur une erreur inattendue.", summary)
        raise
    if single_batch is not None:
        _process_batch(single_batch)


@celery_app.task(name="app.tasks.import_zip_batch", bind=True, soft_time_limit=settings.IMPORT_SOFT_TIME_LIMIT_SECONDS)
def import_zip_batch(self, payload: dict) -> None:
    """One batch of the files of a big archive (see the module)."""
    _process_batch(payload)
