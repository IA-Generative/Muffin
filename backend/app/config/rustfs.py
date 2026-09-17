from pydantic_settings import BaseSettings, SettingsConfigDict


class RustFsSettings(BaseSettings):
    RUSTFS_ENDPOINT_URL: str = "http://localhost:9000"
    RUSTFS_ACCESS_KEY: str = "rustfsadmin"
    RUSTFS_SECRET_KEY: str = "rustfsadmin"
    RUSTFS_BUCKET: str = "muffin-documents"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
