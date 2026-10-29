import functools
import uuid
from collections.abc import Callable, Iterable

from celery import chord
from celery.canvas import Signature
from loguru import logger

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.owui_client import OwuiClient
from app.owui_vectors import OwuiVectors

# A synchronisation is many small tasks (#453), so that a collection that fails or is slow never holds back the
# others: the phases below run one after the other (groups, then knowledge bases, then files, then the closing),
# and inside a phase one task per object runs in parallel (fan-out), the next phase starting when they are all done
# (fan-in).
_MAX_RETRIES = 3
_RETRY_SECONDS = 5


def unit_task(name: str) -> Callable:
    """A task of one object. Tried again a few times - Open WebUI or Muffin may be busy - and then reported as an
    error in its result instead of raised: the tasks of the phase are a chord, which a raised one would cancel.
    A ValueError is a fact about the object (not in S3...), trying again changes nothing."""

    def decorate(function: Callable) -> Callable:
        @celery_app.task(name=name, bind=True)
        @functools.wraps(function)
        def task(self, *args):
            try:
                return function(*args)
            except Exception as error:
                if self.request.called_directly:
                    raise
                if not isinstance(error, ValueError) and self.request.retries < _MAX_RETRIES:
                    raise self.retry(exc=error, countdown=_RETRY_SECONDS * 2**self.request.retries) from error
                logger.exception("{}{} failed", name, args)
                return {
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                    "object": args[-1] if args else None,
                }

        return task

    return decorate


@unit_task("app.tasks.sync_group")
def sync_group(group_id: str) -> dict:
    """Makes Muffin's copy of one Open WebUI group what Open WebUI has (#453): its name and its members.

    Muffin has no table of users - a person is their Keycloak subject - so there is no task per user: the members
    are tied to their subject here, from what they signed in with. A member who signed in some other way (a local
    account) has none, and is left out - a share to the group could not reach them anyway."""
    owui = OwuiClient()
    group = owui.group(group_id)
    members = list(owui.group_members(group_id))
    subjects = sorted({member.keycloak_sub for member in members if member.keycloak_sub})
    unresolved = [member.email for member in members if not member.keycloak_sub]
    if unresolved:
        logger.warning(
            "Group {}: {} member(s) without a Keycloak subject, left out: {}", group.name, len(unresolved), unresolved
        )
    result = backend_client.sync_group("owui", group.id, group.name, group.description or "", subjects)
    logger.info("Group {} synchronised: {}", group.name, result)
    return {**result, "members_without_subject": len(unresolved)}


# The owner a collection gets when the one it had in Open WebUI never signed in through Keycloak: a collection
# needs one, and it is only the other readers (and everyone, if it is public) that can reach it.
_UNKNOWN_OWNER = "owui:{user_id}"


@unit_task("app.tasks.sync_knowledge")
def sync_knowledge(knowledge_id: str) -> dict:
    """Makes Muffin's copy of one Open WebUI knowledge base what Open WebUI has (#453): its name, its owner and
    who may read it. Its groups must have been synchronised before (sync_group): a group Muffin has no copy of
    gets no share, and is reported.

    Only the `read` grants are copied: Muffin has no shared writing yet, so a `write` grant is left out."""
    owui = OwuiClient()
    knowledge = owui.knowledge(knowledge_id)

    owner = owui.user(knowledge.user_id).keycloak_sub
    if owner is None:
        owner = _UNKNOWN_OWNER.format(user_id=knowledge.user_id)
        logger.warning("Knowledge base {}: its owner has no Keycloak subject, owned by {}", knowledge.name, owner)

    public = False
    user_shares: list[dict] = []
    group_ids: list[str] = []
    without_subject = write_grants = 0
    for grant in knowledge.access_grants:
        if grant.permission != "read":
            write_grants += 1
        elif grant.principal_id == "*":
            public = True
        elif grant.principal_type == "group":
            group_ids.append(grant.principal_id)
        else:
            user = owui.user(grant.principal_id)
            if user.keycloak_sub is None:
                without_subject += 1
                logger.warning(
                    "Knowledge base {}: reader {} has no Keycloak subject, left out", knowledge.name, user.email
                )
            else:
                user_shares.append({"subject_id": user.keycloak_sub, "email": user.email})
    if write_grants:
        logger.info(
            "Knowledge base {}: {} write grant(s) not copied (no shared writing in Muffin)",
            knowledge.name,
            write_grants,
        )

    result = backend_client.sync_collection(
        "owui",
        knowledge.id,
        {
            "name": knowledge.name,
            "description": knowledge.description or "",
            "owner_id": owner,
            "embedding_model": owui.embedding_model(),
            "public": public,
            "user_shares": user_shares,
            "group_external_ids": group_ids,
        },
    )
    if result["unknown_groups"]:
        logger.warning(
            "Knowledge base {}: groups not synchronised yet, no share for them: {}",
            knowledge.name,
            result["unknown_groups"],
        )
    logger.info("Knowledge base {} synchronised: {}", knowledge.name, result)
    return {**result, "readers_without_subject": without_subject, "write_grants_ignored": write_grants}


# Muffin's own estimate (worker/document_process/app/chunking.py): good enough for what only sizes a chunk.
_TOKENS_PER_CHAR = 0.25


@unit_task("app.tasks.sync_knowledge_file")
def sync_knowledge_file(knowledge_id: str, file_id: str) -> dict:
    """Makes Muffin's copy of one file of an Open WebUI knowledge base what Open WebUI has (#453).

    Nothing is copied but the rows: the file stays in Open WebUI's bucket (Muffin reads it there), the vectors in
    its Qdrant, and the chunks - text and id of their point - come from that Qdrant. The text is one page: Open
    WebUI's extraction (Tika) keeps no page boundary. The knowledge base must have been synchronised before."""
    owui = OwuiClient()
    file = owui.file(file_id)
    if not file.path or not file.path.startswith("s3://"):
        raise ValueError(f"File {file.filename} is not in S3 (path {file.path!r}): Muffin cannot read it where it is")

    chunks = OwuiVectors().chunks(knowledge_id, file_id)
    if not chunks:
        logger.warning("File {} has no chunk in the knowledge base {}", file.filename, knowledge_id)
    added_by = owui.user(file.user_id) if file.user_id else None

    result = backend_client.sync_document(
        "owui",
        f"{knowledge_id}/{file_id}",
        {
            "collection_external_id": knowledge_id,
            "name": file.filename,
            "storage_key": file.path,
            "content_hash": file.hash,
            "added_by_user_id": added_by.keycloak_sub if added_by else None,
            "added_by_display": added_by.name if added_by else None,
            "text": owui.file_text(file_id),
            "chunks": [
                {
                    "id": chunk.id,
                    "index": index,
                    "text": chunk.text,
                    "token_count": round(len(chunk.text) * _TOKENS_PER_CHAR),
                }
                for index, chunk in enumerate(chunks)
            ],
        },
    )
    logger.info("File {} synchronised: {}", file.filename, result)
    return result


# -- the phases ------------------------------------------------------------------------------------------


def _fan_out(units: Iterable[Signature], next_phase: Signature) -> None:
    """Runs the tasks of a phase together, then `next_phase` with their results. A phase with nothing to do goes
    straight to the next, since a chord of nothing would never call it."""
    units = list(units)
    if units:
        chord(units)(next_phase)
    else:
        next_phase.apply_async(args=([],))


def _errors(results: list) -> list[dict]:
    return [result for result in results if isinstance(result, dict) and result.get("status") == "error"]


@celery_app.task(name="app.tasks.sync_owui")
def sync_owui() -> dict:
    """Root of a synchronisation Open WebUI -> Muffin (#453): lists the groups and starts a task for each."""
    run = {"id": str(uuid.uuid4())}
    group_ids = [group.id for group in OwuiClient().groups()]
    run["group_ids"] = group_ids
    logger.info("Synchronisation {} started: {} group(s)", run["id"], len(group_ids))
    _fan_out((sync_group.s(group_id) for group_id in group_ids), sync_knowledge_bases.s(run))
    return {"run": run["id"], "groups": len(group_ids)}


@celery_app.task(name="app.tasks.sync_knowledge_bases")
def sync_knowledge_bases(group_results: list, run: dict) -> dict:
    """Second phase, once the groups are copied (a knowledge base is shared with them): one task per knowledge base."""
    run["group_errors"] = _errors(group_results)
    knowledge_ids = [knowledge.id for knowledge in OwuiClient().knowledge_bases()]
    run["knowledge_ids"] = knowledge_ids
    logger.info("Synchronisation {}: {} knowledge base(s)", run["id"], len(knowledge_ids))
    _fan_out((sync_knowledge.s(knowledge_id) for knowledge_id in knowledge_ids), sync_files.s(run))
    return {"knowledge_bases": len(knowledge_ids)}


@celery_app.task(name="app.tasks.sync_files")
def sync_files(knowledge_results: list, run: dict) -> dict:
    """Third phase, once the knowledge bases are copied (a file goes into one): one task per file of each.

    A knowledge base whose copy failed, or whose files could not be listed, is left out of the cleaning at the
    end: what is missing from the list is not known to be gone from Open WebUI."""
    errors = _errors(knowledge_results)
    run["knowledge_errors"] = errors
    unsafe = {error["object"] for error in errors}
    owui = OwuiClient()
    pairs: list[tuple[str, str]] = []
    for knowledge_id in run["knowledge_ids"]:
        if knowledge_id in unsafe:
            continue
        try:
            pairs.extend((knowledge_id, file.id) for file in owui.knowledge_files(knowledge_id))
        except Exception:
            logger.exception(
                "Synchronisation {}: the files of knowledge base {} could not be listed", run["id"], knowledge_id
            )
            unsafe.add(knowledge_id)
    run["unsafe_knowledge_ids"] = sorted(unsafe)
    run["document_ids"] = [f"{knowledge_id}/{file_id}" for knowledge_id, file_id in pairs]
    logger.info("Synchronisation {}: {} file(s)", run["id"], len(pairs))
    _fan_out((sync_knowledge_file.s(knowledge_id, file_id) for knowledge_id, file_id in pairs), finish_sync.s(run))
    return {"files": len(pairs)}


def _gone(copied: list[str], seen: list[str], what: str, run_id: str) -> list[str]:
    """What Muffin has copied and Open WebUI no longer lists. If Open WebUI listed none at all while Muffin has
    some, the listing is not trusted (a key that lost its rights lists nothing): nothing is dropped."""
    gone = sorted(set(copied) - set(seen))
    if gone and not seen:
        logger.warning(
            "Synchronisation {}: Open WebUI lists no {} but Muffin has {}: none dropped", run_id, what, len(copied)
        )
        return []
    return gone


@celery_app.task(name="app.tasks.finish_sync")
def finish_sync(file_results: list, run: dict) -> dict:
    """Last phase: drops from Muffin what is gone from Open WebUI - files, then collections, then groups, so that
    nothing is left pointing to what was dropped - and gives the account of the synchronisation."""
    run_id = run["id"]
    unsafe = set(run["unsafe_knowledge_ids"])
    gone_documents = [
        external_id
        for external_id in _gone(
            backend_client.list_synced("synced-documents", "owui"), run["document_ids"], "file", run_id
        )
        if external_id.split("/", 1)[0] not in unsafe
    ]
    gone_collections = _gone(
        backend_client.list_synced("synced-collections", "owui"), run["knowledge_ids"], "knowledge base", run_id
    )
    gone_groups = _gone(backend_client.list_synced("groups", "owui"), run["group_ids"], "group", run_id)
    for kind, ids in (
        ("synced-documents", gone_documents),
        ("synced-collections", gone_collections),
        ("groups", gone_groups),
    ):
        for external_id in ids:
            backend_client.delete_synced(kind, "owui", external_id)

    account = {
        "run": run_id,
        "groups": {"seen": len(run["group_ids"]), "errors": len(run["group_errors"]), "dropped": len(gone_groups)},
        "knowledge_bases": {
            "seen": len(run["knowledge_ids"]),
            "errors": len(run["knowledge_errors"]),
            "unlisted": len(unsafe),
            "dropped": len(gone_collections),
        },
        "files": {
            "seen": len(run["document_ids"]),
            "errors": len(_errors(file_results)),
            "dropped": len(gone_documents),
        },
    }
    errors = run["group_errors"] + run["knowledge_errors"] + _errors(file_results)
    for error in errors:
        logger.error("Synchronisation {}: {}", run_id, error)
    logger.info("Synchronisation {} done: {}", run_id, account)
    return account
