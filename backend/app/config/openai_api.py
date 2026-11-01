from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenAiApiSettings(BaseSettings):
    # The conversations the OpenAI-compatible API makes (#513) are kept this many days, then purged.
    OPENAI_API_RETENTION_DAYS: int = 7
    # How many answers one user may have in the making through the API at once, per pod.
    OPENAI_API_RUNS_PER_USER: int = 3
    # The longest history a request may carry (messages), and the longest message (characters).
    OPENAI_API_MAX_MESSAGES: int = 40
    OPENAI_API_MAX_MESSAGE_CHARS: int = 20000
    # How long a request waits for its answer before the run is cancelled (the ingress cuts at 600 s).
    OPENAI_API_TIMEOUT_SECONDS: int = 540
    # How many models `GET /v1/models` lists besides `muffin`: the top-level collections the key's owner reads.
    OPENAI_API_MAX_LISTED_COLLECTIONS: int = 100

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
