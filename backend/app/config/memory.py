from pydantic_settings import BaseSettings, SettingsConfigDict


class MemorySettings(BaseSettings):
    """What the assistant remembers of a person (#34, #282). The memory itself belongs to the person; these are the
    limits of the application and the switch of the administrator."""

    # The circuit breaker of the administrator: off, nothing is read, written or shown as used - the data stays.
    MEMORY_ENABLED: bool = True
    # The longest a remembered sentence may be, and how many one person may keep.
    MEMORY_VALUE_MAX_CHARS: int = 300
    MEMORY_MAX_ITEMS: int = 100
    # What a run reads at most (characters, about 4 per token): the rest stays out of the prompt.
    MEMORY_PROMPT_MAX_CHARS: int = 2000

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
