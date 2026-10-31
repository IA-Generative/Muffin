import contextlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.agent.runner import agent_runner
from app.config import KeycloakSettings
from app.mcp_server import mcp_app, mcp_lifespan
from app.routers.admin_cgu import router as admin_cgu_router
from app.routers.admin_owui_sync import router as admin_owui_sync_router
from app.routers.admin_prompts import router as admin_prompts_router
from app.routers.admin_reports import router as admin_reports_router
from app.routers.admin_settings import router as admin_settings_router
from app.routers.api_keys import router as api_keys_router
from app.routers.auth import router as auth_router
from app.routers.cgu import router as cgu_router
from app.routers.collection_imports import internal_router as internal_collection_imports_router
from app.routers.collection_imports import router as collection_imports_router
from app.routers.collections import router as collections_router
from app.routers.conversations import router as conversations_router
from app.routers.document_drafts import router as document_drafts_router
from app.routers.document_refresh import internal_router as internal_document_refresh_router
from app.routers.document_refresh import router as document_refresh_router
from app.routers.documents import router as documents_router
from app.routers.filing import router as filing_router
from app.routers.groups import router as groups_router
from app.routers.health import router as health_router
from app.routers.index_rebuilds import internal_router as internal_index_rebuilds_router
from app.routers.index_rebuilds import router as index_rebuilds_router
from app.routers.internal_collection_sync import router as internal_collection_sync_router
from app.routers.internal_collections import router as internal_collections_router
from app.routers.internal_conversations import router as internal_conversations_router
from app.routers.internal_document_drafts import router as internal_document_drafts_router
from app.routers.internal_document_sync import router as internal_document_sync_router
from app.routers.internal_documents import router as internal_documents_router
from app.routers.internal_edit_requests import router as internal_edit_requests_router
from app.routers.internal_evaluation import router as internal_evaluation_router
from app.routers.internal_groups import router as internal_groups_router
from app.routers.internal_llm import router as internal_llm_router
from app.routers.internal_owui_sync import router as internal_owui_sync_router
from app.routers.internal_pipeline import router as internal_pipeline_router
from app.routers.internal_prompts import router as internal_prompts_router
from app.routers.internal_runs import router as internal_runs_router
from app.routers.internal_tasks import router as internal_tasks_router
from app.routers.living_documents import router as living_documents_router
from app.routers.models import router as models_router
from app.routers.qa_pairs import router as qa_pairs_router
from app.routers.qa_suggestions import router as qa_suggestions_router
from app.routers.quality import router as quality_router
from app.routers.reports import router as reports_router
from app.routers.runs import router as runs_router
from app.routers.tasks import router as tasks_router
from app.routers.usage import router as usage_router
from app.services.copied_collections import CopiedCollectionError

_keycloak_settings = KeycloakSettings()


@contextlib.asynccontextmanager
async def lifespan(application: FastAPI):
    """What runs for as long as the API does: the MCP server's sessions, and the agent's runs (which are tasks of this
    process: they are started here, and the ones still going are failed cleanly when it stops)."""
    async with mcp_lifespan(application):
        await agent_runner.start_up()
        try:
            yield
        finally:
            await agent_runner.shut_down()


app = FastAPI(
    lifespan=lifespan,
    title="Muffin API",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redocs",
    openapi_url="/api/openapi.json",
    openapi_tags=[
        {
            "name": "Auth",
            "description": "Login/logout via Keycloak, session management.",
        },
        {
            "name": "Health",
            "description": "Liveness/readiness of the API and its dependencies.",
        },
        {
            "name": "Models",
            "description": "LLM models available for chat, as served by the LLM hub.",
        },
        {
            "name": "Collections",
            "description": "Collections owned by the current user.",
        },
        {
            "name": "Documents",
            "description": "Documents within a collection: upload, register a URL, delete.",
        },
        {
            "name": "Tasks",
            "description": "Background tasks dispatched on the user's behalf: status, revocation.",
        },
        {
            "name": "Runs",
            "description": "Research agent runs: create, status/events, cancellation.",
        },
        {
            "name": "Conversations",
            "description": "Chat conversations and their message history.",
        },
        {"name": "Admin", "description": "Global, admin-only settings."},
        {
            "name": "Internal",
            "description": "Worker-to-backend calls, authenticated via a shared API key.",
        },
    ],
)


@app.exception_handler(CopiedCollectionError)
async def copied_collection_handler(_request: Request, _error: CopiedCollectionError) -> JSONResponse:
    """What is in a copy of another system's collection is changed there, not here (#464)."""
    return JSONResponse(
        status_code=409,
        content={
            "detail": "This collection is a copy of another system's: change it there, or have Muffin take it over"
        },
    )


# Explicit origin (not "*") required: credentialed cookie requests are
# rejected by browsers if allow_origins is a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_keycloak_settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(api_keys_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(collections_router, prefix="/api")
app.include_router(groups_router, prefix="/api")
app.include_router(qa_pairs_router, prefix="/api")
app.include_router(qa_suggestions_router, prefix="/api")
app.include_router(collection_imports_router, prefix="/api")
app.include_router(internal_collection_imports_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(index_rebuilds_router, prefix="/api")
app.include_router(internal_index_rebuilds_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(document_refresh_router, prefix="/api")
app.include_router(internal_document_refresh_router, prefix="/api")
app.include_router(living_documents_router, prefix="/api")
app.include_router(document_drafts_router, prefix="/api")
app.include_router(filing_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(admin_settings_router, prefix="/api")
app.include_router(admin_prompts_router, prefix="/api")
app.include_router(admin_owui_sync_router, prefix="/api")
app.include_router(admin_cgu_router, prefix="/api")
app.include_router(cgu_router, prefix="/api")
app.include_router(admin_reports_router, prefix="/api")
app.include_router(internal_groups_router, prefix="/api")
app.include_router(internal_collection_sync_router, prefix="/api")
app.include_router(internal_document_sync_router, prefix="/api")
app.include_router(internal_owui_sync_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(quality_router, prefix="/api")
app.include_router(usage_router, prefix="/api")
app.include_router(internal_documents_router, prefix="/api")
app.include_router(internal_document_drafts_router, prefix="/api")
app.include_router(internal_edit_requests_router, prefix="/api")
app.include_router(internal_evaluation_router, prefix="/api")
app.include_router(internal_conversations_router, prefix="/api")
app.include_router(internal_collections_router, prefix="/api")
app.include_router(internal_pipeline_router, prefix="/api")
app.include_router(internal_tasks_router, prefix="/api")
app.include_router(internal_llm_router, prefix="/api")
app.include_router(internal_runs_router, prefix="/api")
app.include_router(internal_prompts_router, prefix="/api")

# The MCP server (#467), under /api/mcp, with its own bearer-token check.
app.mount("/api/mcp", mcp_app)
