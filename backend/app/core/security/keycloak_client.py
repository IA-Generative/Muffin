from keycloak import KeycloakOpenID

from app.config import KeycloakSettings
from app.connectors import redis_connector
from app.core.security.session import SessionStore

keycloak_settings = KeycloakSettings()

keycloak_openid = KeycloakOpenID(
    server_url=keycloak_settings.KEYCLOAK_URL,
    client_id=keycloak_settings.KEYCLOAK_CLIENT_ID,
    realm_name=keycloak_settings.KEYCLOAK_REALM,
    client_secret_key=keycloak_settings.KEYCLOAK_CLIENT_SECRET,
)

session_store = SessionStore(
    redis_client=redis_connector.client,
    keycloak_openid=keycloak_openid,
    ttl_seconds=keycloak_settings.SESSION_TTL_SECONDS,
)
