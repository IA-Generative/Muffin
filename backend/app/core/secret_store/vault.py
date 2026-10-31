import asyncio
import base64
import time
from typing import Any

import httpx
from loguru import logger

from app.config import SecretsSettings
from app.core.secret_store.errors import SecretDecryptionError, SecretsNotConfiguredError, SecretUnavailableError

# The version of a key does not change but when someone rotates it: looked up again after this long.
_VERSION_TTL_SECONDS = 60.0
# A token is renewed (a new login) once this part of its lease has passed.
_LEASE_USED = 0.8


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class VaultTransitProvider:
    """Vault's Transit engine (#521): the application hands over the secret to encrypt and gets back text that only
    Vault can open, so the key never reaches the application or the database. The key is `derived`: the context given
    with each call - the id, the owner and the purpose of the row - is part of what is encrypted, and the text opens
    nowhere else. Rotating the key and rewrapping the texts (`rewrap`) never shows a secret to the application."""

    name = "vault"

    def __init__(self, settings: SecretsSettings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.VAULT_ADDR:
            raise SecretsNotConfiguredError("VAULT_ADDR is not set")
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.VAULT_ADDR.rstrip("/"),
            timeout=settings.VAULT_TIMEOUT_SECONDS,
            verify=settings.VAULT_CA_CERT or True,
        )
        self._token = ""
        self._token_until = 0.0
        self._login_lock = asyncio.Lock()
        self._version: tuple[str, float] | None = None

    async def encrypt(self, plaintext: str, *, context: str) -> str:
        data = await self._call("encrypt", {"plaintext": _b64(plaintext), "context": _b64(context)})
        return data["ciphertext"]

    async def decrypt(self, ciphertext: str, *, context: str) -> str:
        data = await self._call("decrypt", {"ciphertext": ciphertext, "context": _b64(context)})
        return base64.b64decode(data["plaintext"]).decode()

    async def rewrap(self, ciphertext: str, *, context: str) -> str:
        """The same secret under the latest version of the key, without it being shown to this process."""
        data = await self._call("rewrap", {"ciphertext": ciphertext, "context": _b64(context)})
        return data["ciphertext"]

    async def current_version(self) -> str:
        """The latest version of the key, as `v3`: what an encryption made now would carry. Read by encrypting - the
        application is allowed to encrypt, not to read the key's own properties."""
        now = time.monotonic()
        if self._version is None or now - self._version[1] > _VERSION_TTL_SECONDS:
            probe = await self.encrypt("version", context="version")
            self._version = (self.version_of(probe), now)
        return self._version[0]

    @staticmethod
    def version_of(ciphertext: str) -> str:
        """The version of the key a ciphertext was made with: `vault:v3:...` is `v3`."""
        parts = ciphertext.split(":", 2)
        return parts[1] if len(parts) == 3 else ""

    async def _call(self, operation: str, payload: dict[str, str]) -> dict[str, Any]:
        settings = self._settings
        path = f"/v1/{settings.VAULT_TRANSIT_MOUNT}/{operation}/{settings.VAULT_TRANSIT_KEY}"
        for attempt in (0, 1):
            headers = {"X-Vault-Token": await self._get_token(renew=attempt == 1)}
            if settings.VAULT_NAMESPACE:
                headers["X-Vault-Namespace"] = settings.VAULT_NAMESPACE
            try:
                response = await self._client.post(path, json=payload, headers=headers)
            except httpx.HTTPError as error:
                raise SecretUnavailableError("Vault cannot be reached") from error
            # A token that Vault no longer knows (revoked, or expired before its renewal): one new login, then give up.
            if response.status_code == 403 and attempt == 0 and settings.VAULT_AUTH_METHOD == "kubernetes":
                continue
            break
        if response.status_code == 400:
            # Transit's answer to a text that does not open: altered, or made for another context.
            raise SecretDecryptionError("The ciphertext does not open")
        if response.status_code >= 400:
            # What Vault says of itself ("permission denied", "Vault is sealed"): never a secret.
            logger.error(f"Vault answered {response.status_code} to {operation}: {self._errors(response)}")
            raise SecretUnavailableError(f"Vault answered {response.status_code}")
        return response.json()["data"]

    @staticmethod
    def _errors(response: httpx.Response) -> str:
        try:
            return "; ".join(response.json().get("errors", []))
        except ValueError:
            return ""

    async def _get_token(self, renew: bool = False) -> str:
        settings = self._settings
        if settings.VAULT_AUTH_METHOD == "token":
            token = settings.VAULT_TOKEN.get_secret_value()
            if not token:
                raise SecretsNotConfiguredError("VAULT_TOKEN is not set")
            return token
        if settings.VAULT_AUTH_METHOD != "kubernetes":
            raise SecretsNotConfiguredError(f"Unknown VAULT_AUTH_METHOD {settings.VAULT_AUTH_METHOD!r}")
        async with self._login_lock:
            if renew or not self._token or time.monotonic() >= self._token_until:
                await self._login()
            return self._token

    async def _login(self) -> None:
        """Exchanges the pod's service account token for a short token of Vault, bound to a role."""
        settings = self._settings
        try:
            jwt = await asyncio.to_thread(lambda: open(settings.VAULT_K8S_JWT_PATH).read().strip())  # noqa: SIM115
        except OSError as error:
            raise SecretsNotConfiguredError("The service account token of the pod cannot be read") from error
        try:
            response = await self._client.post(
                f"/v1/auth/{settings.VAULT_K8S_AUTH_MOUNT}/login", json={"role": settings.VAULT_K8S_ROLE, "jwt": jwt}
            )
        except httpx.HTTPError as error:
            raise SecretUnavailableError("Vault cannot be reached") from error
        if response.status_code != 200:
            logger.error(f"Vault refused the login of the pod ({response.status_code}): {self._errors(response)}")
            raise SecretUnavailableError("Vault refused the login")
        auth = response.json()["auth"]
        self._token = auth["client_token"]
        self._token_until = time.monotonic() + float(auth.get("lease_duration", 0)) * _LEASE_USED

    async def aclose(self) -> None:
        await self._client.aclose()
