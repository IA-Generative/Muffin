import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.tool import (
    ConversationToolsUpdate,
    ToolDecision,
    ToolOut,
    ToolProposalOut,
    ToolServerCreate,
    ToolServerOut,
    ToolServerUpdate,
)
from app.services.tool_service import ToolService

router = APIRouter(tags=["Tools"])


def get_tool_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ToolService:
    return ToolService(db)


ServiceDep = Annotated[ToolService, Depends(get_tool_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/tools",
    summary="The tools the caller may use - Muffin's own and those of the servers they can see - and which ones a "
    "conversation has removed",
    response_model=list[ToolOut],
)
async def list_tools(
    user: UserDep, service: ServiceDep, conversation_id: Annotated[uuid.UUID | None, Query()] = None
) -> list[ToolOut]:
    return await service.available(user.user_id, user.groups, conversation_id)


@router.put(
    "/conversations/{conversation_id}/tools",
    summary="Remove tools for a conversation (the whole list): the model is not given them. Only ever removes.",
    response_model=list[str],
)
async def set_conversation_tools(
    conversation_id: uuid.UUID, body: ConversationToolsUpdate, user: UserDep, service: ServiceDep
) -> list[str]:
    return await service.set_disabled(user, conversation_id, body.disabled_refs)


@router.get("/tool-servers", summary="The MCP servers the caller added or can use", response_model=list[ToolServerOut])
async def list_servers(user: UserDep, service: ServiceDep) -> list[ToolServerOut]:
    return await service.list_servers(user)


@router.post(
    "/tool-servers",
    summary="Add an MCP server: its address is checked (public, allowed domain), its tools are imported",
    status_code=status.HTTP_201_CREATED,
    response_model=ToolServerOut,
)
async def create_server(body: ToolServerCreate, user: UserDep, service: ServiceDep) -> ToolServerOut:
    return await service.create_server(user, body)


@router.get("/tool-servers/{server_id}", response_model=ToolServerOut)
async def get_server(server_id: uuid.UUID, user: UserDep, service: ServiceDep) -> ToolServerOut:
    return await service.get_server(user, server_id)


@router.patch("/tool-servers/{server_id}", response_model=ToolServerOut)
async def update_server(
    server_id: uuid.UUID, body: ToolServerUpdate, user: UserDep, service: ServiceDep
) -> ToolServerOut:
    return await service.update_server(user, server_id, body)


@router.delete("/tool-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    await service.delete_server(user, server_id)


@router.post(
    "/tool-servers/{server_id}/sync",
    summary="Import the tools of the server again (`tools/list`) - also a test of the connection",
    response_model=ToolServerOut,
)
async def sync_server(server_id: uuid.UUID, user: UserDep, service: ServiceDep) -> ToolServerOut:
    return await service.sync_server(user, server_id)


@router.get(
    "/conversations/{conversation_id}/tool-calls",
    summary="The requests to run a tool that changes data, made in this conversation - waiting or decided",
    response_model=list[ToolProposalOut],
)
async def list_conversation_tool_calls(
    conversation_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> list[ToolProposalOut]:
    return await service.proposals_for_conversation(conversation_id, user.user_id)


@router.post(
    "/runs/{run_id}/tool-calls/decision",
    summary="Authorise or refuse, together, the requests to run a tool that one turn made. What is authorised runs "
    "with the rights the caller has now; the outcome is written into the conversation. A second answer finds "
    "nothing to decide.",
    response_model=list[ToolProposalOut],
)
async def decide_tool_calls(
    run_id: uuid.UUID, body: ToolDecision, user: UserDep, service: ServiceDep
) -> list[ToolProposalOut]:
    return await service.decide(user, run_id, body.approve)
