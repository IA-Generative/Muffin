from pydantic_settings import BaseSettings, SettingsConfigDict


class RunSettings(BaseSettings):
    # How many sub-collections a pinned collection brings along with it (#220). Every pinned
    # collection is searched, one index query each, so pinning a collection with a large subtree
    # would slow down every search of the run; the nearest ones (by level) are pinned and the
    # rest is left to the "go further" exploration (#219).
    PINNED_DESCENDANTS_LIMIT: int = 30

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
