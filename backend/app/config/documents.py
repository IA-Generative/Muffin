from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentSettings(BaseSettings):
    # How long a living document's edit lock (#170) stays valid without being renewed. Short
    # enough that an abandoned browser tab frees the document on its own, long enough that
    # reading a preview before validating it doesn't expire mid-way - clients renew it while
    # the preview is open.
    DOCUMENT_LOCK_TTL_SECONDS: int = 600
    # The largest file one may upload, in bytes - unset, no limit. A file is streamed to the object
    # store, never held whole in memory, whatever its size.
    DOCUMENT_MAX_UPLOAD_BYTES: int | None = None

    # A ZIP import (#335) has at most this many of its documents being extracted at a time: the others wait,
    # not in the queue, and the end of an extraction releases the next one. So an archive of 2000 files
    # never fills the queue, and several imports - and the uploads of everyone else - share the pod.
    IMPORT_PROCESSING_WINDOW: int = 4
    # A document released but not extracted after this long stops holding its place: a task lost on the way
    # (queue flushed, worker killed for good) must not block its import for ever. The worker's own task
    # limits are shorter than this.
    IMPORT_SLOT_TIMEOUT_SECONDS: int = 4 * 60 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
