from pydantic_settings import BaseSettings, SettingsConfigDict


class RustFsSettings(BaseSettings):
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
