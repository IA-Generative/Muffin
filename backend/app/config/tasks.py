from pydantic_settings import BaseSettings, SettingsConfigDict


class TaskSettings(BaseSettings):
    # A task still STARTED after this long is considered lost (its worker died, and Celery will
    # not report it) and the reaper marks it failed. Generous: well past the workers' soft time
    # limit (2 h) and broker visibility timeout (4 h), so a genuinely long task is never cut.
    TASK_STUCK_AFTER_HOURS: int = 24

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
