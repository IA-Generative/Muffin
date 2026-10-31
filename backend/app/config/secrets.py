from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecretsSettings(BaseSettings):
    """Where the secrets Muffin must read back (the key of a service it calls for a user, a connector's token) are
    encrypted (#521): in Vault, which keeps the key out of the application and of the database, or - for a development
    machine and a deployment with no Vault - with a key ring of its own."""

    # "vault" or "local".
    SECRETS_PROVIDER: str = "local"
    # Refuse to start unless Vault is the provider: for a production, where "local" would only be a mistake.
    SECRETS_REQUIRE_VAULT: bool = False

    # The key ring of the local provider: `id=base64 of 32 bytes` separated by commas, the first being the one that
    # encrypts and the others only decrypting, so that a key is changed without losing a secret.
    SECRETS_LOCAL_KEYS: SecretStr = SecretStr("")

    VAULT_ADDR: str = ""
    # The Transit engine's mount and the key (created with `derived=true`: the context binds a secret to its row).
    VAULT_TRANSIT_MOUNT: str = "transit"
    VAULT_TRANSIT_KEY: str = "muffin-secrets"
    # Enterprise only: the namespace.
    VAULT_NAMESPACE: str = ""
    # "kubernetes" (the pod's service account, a short token Vault renews) or "token" (a given token: development).
    VAULT_AUTH_METHOD: str = "kubernetes"
    VAULT_TOKEN: SecretStr = SecretStr("")
    VAULT_K8S_ROLE: str = "muffin"
    VAULT_K8S_AUTH_MOUNT: str = "kubernetes"
    VAULT_K8S_JWT_PATH: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    # The certificate authority of Vault, when it is not one the system knows.
    VAULT_CA_CERT: str = ""
    VAULT_TIMEOUT_SECONDS: float = 5.0

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
