from pydantic import BaseModel


class SecretsStatusOut(BaseModel):
    """Where the secrets are encrypted, and how far a rotation of the key has got - never a secret."""

    provider: str
    # False when the provider cannot be reached or is not configured: what needs fixing is in the logs, not here.
    reachable: bool
    current_version: str | None
    # How many secrets there are per version of the key.
    versions: dict[str, int]
    # How many are not on the current version: what a rewrap has left to do.
    stale: int


class RewrapOut(BaseModel):
    rewrapped: int
    remaining: int
    current_version: str
