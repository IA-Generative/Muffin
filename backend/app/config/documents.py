from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentSettings(BaseSettings):
    # How long a living document's edit lock (#170) stays valid without being renewed. Short
    # enough that an abandoned browser tab frees the document on its own, long enough that
    # reading a preview before validating it doesn't expire mid-way - clients renew it while
    # the preview is open.
    DOCUMENT_LOCK_TTL_SECONDS: int = 600
    # Largest ZIP accepted for an import (#223), in bytes - checked on upload, before anything is
    # stored. What the archive expands to is bounded separately, worker-side (ZIP_IMPORT_*).
    ZIP_IMPORT_MAX_UPLOAD_BYTES: int = 500 * 1024 * 1024

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
