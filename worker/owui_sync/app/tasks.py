from loguru import logger

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.owui_client import OwuiClient


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
