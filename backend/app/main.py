from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import KeycloakSettings
from app.routers.auth import router as auth_router
from app.routers.collections import router as collections_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.routers.internal_documents import router as internal_documents_router
from app.routers.models import router as models_router

_keycloak_settings = KeycloakSettings()

app = FastAPI(
    title="Muffin API",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redocs",
    openapi_url="/api/openapi.json",
    openapi_tags=[
        {"name": "Auth", "description": "Login/logout via Keycloak, session management."},
        {"name": "Health", "description": "Liveness/readiness of the API and its dependencies."},
        {"name": "Models", "description": "LLM models available for chat, as served by the LLM hub."},
        {"name": "Collections", "description": "Collections owned by the current user."},
        {"name": "Documents", "description": "Documents within a collection: upload, register a URL, delete."},
        {"name": "Internal", "description": "Worker-to-backend calls, authenticated via a shared API key."},
    ],
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
app.include_router(health_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(collections_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(internal_documents_router, prefix="/api")
