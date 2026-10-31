from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiKeySettings(BaseSettings):
    # The secrets the keys are hashed with (#521), `version=secret` separated by commas, the first being the one new
    # keys are hashed with and the others only checked: "v2=...,v1=..." to rotate without cutting a key off. A key is
    # stored as HMAC-SHA256 of it under one of these - a copy of the database alone is of no use to forge or check one.
    # Empty means personal API keys are off (checked at request time, like the share invitations' pepper).
    API_KEY_PEPPERS: SecretStr = SecretStr("")
    # How many keys a user may have at once (not counting the revoked and the expired).
    API_KEYS_PER_USER: int = 10
    # A key always expires: what it may be set to at most, in days.
    API_KEY_MAX_DAYS: int = 365
    API_KEY_DEFAULT_DAYS: int = 90
    # What one key may do per minute, whatever it asks for.
    API_KEY_RATE_LIMIT_PER_MINUTE: int = 120

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    @property
    def peppers(self) -> list[tuple[str, str]]:
        """(version, secret) for each pepper set, the one new keys use first."""
        out: list[tuple[str, str]] = []
        for item in self.API_KEY_PEPPERS.get_secret_value().split(","):
            version, separator, secret = item.strip().partition("=")
            if separator and version.strip() and secret.strip():
                out.append((version.strip(), secret.strip()))
        return out

    @property
    def enabled(self) -> bool:
        return bool(self.peppers)
