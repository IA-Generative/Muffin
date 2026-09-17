from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    OPENAI_API_KEY: str = ""
    # No default: unlike a hardcoded public OpenAI fallback, an empty value
    # makes /api/models fail loudly instead of silently billing someone else's hub.
    OPENAI_API_BASE_URL: str = ""
    CHAT_MODELS_CACHE_TTL_SECONDS: int = 3600

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    @property
    def is_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY and self.OPENAI_API_BASE_URL)
