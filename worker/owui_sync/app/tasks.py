from loguru import logger

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.owui_client import OwuiClient
from app.owui_vectors import OwuiVectors


@celery_app.task(name="app.tasks.sync_owui")
def sync_owui() -> dict:
    """Root of a synchronisation Open WebUI -> Muffin (#453). The tasks that read Open WebUI and write
    Muffin come with the following steps."""
    logger.info("Open WebUI synchronisation requested")
    return {"status": "nothing_to_do"}


@celery_app.task(name="app.tasks.sync_group")
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


@celery_app.task(name="app.tasks.sync_knowledge")
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


@celery_app.task(name="app.tasks.sync_knowledge_file")
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
