import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.secret_store.errors import SecretDecryptionError, SecretsNotConfiguredError

_PREFIX = "local"
_NONCE_BYTES = 12


def parse_key_ring(raw: str) -> list[tuple[str, bytes]]:
    """(id, key) for each `id=base64` of the ring, the first being the one that encrypts."""
    ring: list[tuple[str, bytes]] = []
    for item in raw.split(","):
        key_id, separator, encoded = item.strip().partition("=")
        if not separator or not key_id.strip() or not encoded.strip():
            continue
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError) as error:
            raise SecretsNotConfiguredError(f"The local key {key_id.strip()!r} is not base64") from error
        if len(key) != 32:
            raise SecretsNotConfiguredError(f"The local key {key_id.strip()!r} must be 32 bytes (AES-256)")
        ring.append((key_id.strip(), key))
    return ring


class LocalProvider:
    """AES-256-GCM with a key ring held in the configuration (a Kubernetes secret): for development, the tests and a
    deployment with no Vault. The same guarantees about what is stored (a unique nonce each time, and the context
    authenticated so that a ciphertext opens only where it was made), without the key leaving the application."""

    name = "local"

    def __init__(self, ring: list[tuple[str, bytes]]) -> None:
        if not ring:
            raise SecretsNotConfiguredError("No local key is set (SECRETS_LOCAL_KEYS)")
        self._ring = ring

    async def encrypt(self, plaintext: str, *, context: str) -> str:
        key_id, key = self._ring[0]
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(key).encrypt(nonce, plaintext.encode(), context.encode())
        return f"{_PREFIX}:{key_id}:{base64.b64encode(nonce + sealed).decode()}"

    async def decrypt(self, ciphertext: str, *, context: str) -> str:
        prefix, _, rest = ciphertext.partition(":")
        key_id, _, encoded = rest.partition(":")
        key = dict(self._ring).get(key_id)
        if prefix != _PREFIX or key is None:
            raise SecretDecryptionError("Not a ciphertext of this provider, or its key is no longer in the ring")
        try:
            raw = base64.b64decode(encoded, validate=True)
            return AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], context.encode()).decode()
        except (InvalidTag, binascii.Error, ValueError) as error:
            raise SecretDecryptionError("The ciphertext does not open") from error

    async def rewrap(self, ciphertext: str, *, context: str) -> str:
        return await self.encrypt(await self.decrypt(ciphertext, context=context), context=context)

    async def current_version(self) -> str:
        return self._ring[0][0]

    @staticmethod
    def version_of(ciphertext: str) -> str:
        """The id of the key a ciphertext was made with."""
        return ciphertext.split(":", 2)[1] if ciphertext.count(":") >= 2 else ""
