"""The secrets Muffin must read back (#521): encrypted before they are stored, opened only where they are used.

`SecretProvider` is what encrypts: `VaultTransitProvider` in production - the key stays in Vault - and `LocalProvider`
(AES-256-GCM, a key ring in the configuration) for development and a deployment with no Vault. Nothing falls back from
one to the other: a provider that cannot answer fails the function that needed it."""

from typing import Protocol

from loguru import logger

from app.config import SecretsSettings
from app.core.secret_store.errors import (
    SecretDecryptionError,
    SecretsNotConfiguredError,
    SecretStoreError,
    SecretUnavailableError,
)
from app.core.secret_store.local import LocalProvider, parse_key_ring
from app.core.secret_store.vault import VaultTransitProvider


class SecretProvider(Protocol):
    name: str

    async def encrypt(self, plaintext: str, *, context: str) -> str: ...

    async def decrypt(self, ciphertext: str, *, context: str) -> str: ...

    async def rewrap(self, ciphertext: str, *, context: str) -> str:
        """The same secret under the latest version of the key."""
        ...

    async def current_version(self) -> str:
        """The version of the key an encryption made now would carry."""
        ...

    @staticmethod
    def version_of(ciphertext: str) -> str:
        """The version of the key a ciphertext carries."""
        ...


def build_provider(settings: SecretsSettings) -> SecretProvider:
    if settings.SECRETS_REQUIRE_VAULT and settings.SECRETS_PROVIDER != "vault":
        raise SecretsNotConfiguredError("SECRETS_REQUIRE_VAULT is set, and the provider is not Vault")
    if settings.SECRETS_PROVIDER == "vault":
        return VaultTransitProvider(settings)
    if settings.SECRETS_PROVIDER == "local":
        return LocalProvider(parse_key_ring(settings.SECRETS_LOCAL_KEYS.get_secret_value()))
    raise SecretsNotConfiguredError(f"Unknown SECRETS_PROVIDER {settings.SECRETS_PROVIDER!r}")


def check_configuration(settings: SecretsSettings) -> None:
    """Run when the application starts: refuses to start a deployment that asked for Vault and has none, and says so
    when secrets are kept with the local key ring."""
    if settings.SECRETS_REQUIRE_VAULT and settings.SECRETS_PROVIDER != "vault":
        raise SecretsNotConfiguredError("SECRETS_REQUIRE_VAULT is set, and SECRETS_PROVIDER is not 'vault'")
    if settings.SECRETS_PROVIDER == "vault":
        if not settings.VAULT_ADDR:
            raise SecretsNotConfiguredError("SECRETS_PROVIDER is 'vault' and VAULT_ADDR is not set")
        return
    if settings.SECRETS_PROVIDER != "local":
        raise SecretsNotConfiguredError(f"Unknown SECRETS_PROVIDER {settings.SECRETS_PROVIDER!r}")
    if settings.SECRETS_LOCAL_KEYS.get_secret_value().strip():
        parse_key_ring(settings.SECRETS_LOCAL_KEYS.get_secret_value())
        logger.warning(
            "Secrets are encrypted with the local key ring: use Vault (SECRETS_PROVIDER=vault) in production"
        )
    else:
        logger.info("No secret is stored: SECRETS_LOCAL_KEYS is not set (and SECRETS_PROVIDER is not 'vault')")


_provider: SecretProvider | None = None


def get_provider() -> SecretProvider:
    global _provider
    if _provider is None:
        _provider = build_provider(SecretsSettings())
    return _provider


def reset_provider() -> None:
    """Forgets the provider built: for tests, and for a configuration that changed."""
    global _provider
    _provider = None


__all__ = [
    "LocalProvider",
    "SecretDecryptionError",
    "SecretProvider",
    "SecretStoreError",
    "SecretUnavailableError",
    "SecretsNotConfiguredError",
    "VaultTransitProvider",
    "build_provider",
    "check_configuration",
    "get_provider",
    "reset_provider",
]
