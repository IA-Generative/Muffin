class SecretStoreError(Exception):
    """Base of what can go wrong with a stored secret. None of these ever carries a secret or a key."""


class SecretsNotConfiguredError(SecretStoreError):
    """No key to encrypt with, or no Vault to ask: nothing is encrypted without one, and nothing falls back to less."""


class SecretUnavailableError(SecretStoreError):
    """The provider cannot be reached or refuses the application: the function that needed the secret fails, loudly."""


class SecretDecryptionError(SecretStoreError):
    """A ciphertext that does not open: altered, made for another row, or with a key that is no longer there."""
