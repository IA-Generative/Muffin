from pydantic_settings import BaseSettings, SettingsConfigDict


class SharingSettings(BaseSettings):
    # Server-side pepper for HMAC-hashing the email/group identifier of a pending collection
    # share (see app/core/sharing.py) - a plain hash of an email/group name is trivially
    # reversible by dictionary attack given how little entropy those values have, so the hash
    # alone must never be enough to recover the identifier. Empty means share invitations are
    # disabled (checked at request time, not at import time) rather than silently hashing unpeppered.
    SHARE_INVITE_PEPPER: str = ""

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
