from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # The queues of this image (#291), each consumed by its own pod - started with `-Q`, see
    # docker-compose.yaml and the Helm values. Names shared with the backend's app/core/tasks.py.
    # Extraction (CPU: OCR, parsing, fetching a URL), prefork. A document a ZIP import created is sent
    # with a low priority (the backend's BULK_PRIORITY): Redis keeps it in a list of its own that the
    # worker only reads once the normal one is empty - a file someone just dropped never waits behind
    # a 2000-file archive.
    EXTRACTION_QUEUE_NAME: str = "document_extraction"
    # Enrichment (network: embeddings and LLM calls), a pool of threads.
    ENRICHMENT_QUEUE_NAME: str = "document_enrichment"
    # Long I/O jobs, with the index rebuilds: reading a ZIP into documents (#223).
    IMPORT_QUEUE_NAME: str = "document_import"
    # The blue/green index rebuilds (#12) - must match INDEX_REBUILD_QUEUE on the backend.
    REBUILD_QUEUE_NAME: str = "index_rebuild"
    # The single queue every task used before #291: still consumed by the extraction pod for one
    # release, so what was queued before the deploy is not lost. To remove after.
    LEGACY_QUEUE_NAME: str = "document_processing"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"

    # Tesseract language code (ISO 639-2). "fra" covers French by default;
    # override per-deployment if most documents are in another language.
    OCR_LANGUAGE: str = "fra"

    # ZIP import (#223): what an archive may expand to. Over ZIP_IMPORT_MAX_FILES files or
    # ZIP_IMPORT_MAX_TOTAL_BYTES once decompressed, the whole archive is refused; a single file
    # over ZIP_IMPORT_MAX_FILE_BYTES, compressed more than ZIP_IMPORT_MAX_RATIO times, or more
    # than ZIP_IMPORT_MAX_DEPTH folders deep is skipped and listed in the summary.
    ZIP_IMPORT_MAX_FILES: int = 2000
    ZIP_IMPORT_MAX_TOTAL_BYTES: int = 2 * 1024 * 1024 * 1024
    ZIP_IMPORT_MAX_FILE_BYTES: int = 200 * 1024 * 1024
    ZIP_IMPORT_MAX_RATIO: int = 100
    ZIP_IMPORT_MAX_DEPTH: int = 20
    TESSDATA_PATH: str | None = None

    # The scheduled refresh of URL documents (#19): the minutes of each hour the beat (run inside each
    # worker, see the Dockerfile's `-B`) looks for documents due for one - on the hour and at half
    # past, the times a schedule can be set to. Several replicas each running their own beat is
    # harmless: the backend hands each due document to one scan only.
    URL_REFRESH_SCAN_MINUTES: str = "0,30"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
