from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    # Whether anyone may make an assistant public in the organisation (#514). Off: only a platform administrator can,
    # and an administrator can always take a public assistant down.
    ASSISTANTS_PUBLIC_ENABLED: bool = False
    # How many assistants a person may author.
    ASSISTANTS_PER_USER: int = 100

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
