from typing import Literal

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

    # What bounds a task (#294): no task is killed for being big, only an operation that does not
    # come back is. A hung parse is killed after OCR_PARSE_TIMEOUT_SECONDS (the parser's own worker
    # process, so the task itself carries on and fails cleanly). Every task also has a soft limit as a
    # safety net - an exception raised in the task, never a kill - and the long ones their own below.
    OCR_PARSE_TIMEOUT_SECONDS: int = 60 * 60
    TASK_SOFT_TIME_LIMIT_SECONDS: int = 2 * 60 * 60
    # A ZIP import over this ends as failed, with a summary of what was created (never left running).
    IMPORT_SOFT_TIME_LIMIT_SECONDS: int = 2 * 60 * 60
    # An index rebuild is resumable, so it runs in slices: when one ends, the next task carries on
    # from what the database says is left. Over REBUILD_MAX_SLICES slices (24 h by default), it fails.
    REBUILD_SLICE_SECONDS: int = 3 * 60 * 60
    REBUILD_MAX_SLICES: int = 8
    # How long Redis waits for a task to be acknowledged before handing it to another worker (tasks
    # acknowledge when they end, `acks_late`). Above every limit here, or a long task would run twice
    # at once; it is also how long a task whose worker died waits to be run again.
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 4 * 60 * 60
    # Fetching a URL: connecting to the site - short, a site down fails fast - then the whole download,
    # a file served by it included - long, a large PDF from a slow site takes a while.
    URL_FETCH_CONNECT_TIMEOUT_SECONDS: int = 30
    # A long document's chunking (911 pages: hundreds of LLM windows, thousands of chunks): how many
    # windows the "llm" strategy asks the model about at once, and how many chunks one embedding call
    # takes - one call per chunk, one after the other, would take hours.
    CHUNKING_LLM_CONCURRENCY: int = 8
    EMBED_BATCH_SIZE: int = 64
    # The pages of a file written (its screenshot stored, its text sent) this many at a time.
    PAGE_WRITE_CONCURRENCY: int = 8
    # A PDF of more than PARSE_RANGE_PAGES pages is extracted in ranges of that many pages, each by a task
    # of its own (parse_page_range), PARSE_WINDOW of them at a time: a range that ends starts the next, so
    # the queue never holds more than that of a document. Each range has its own OCR_PARSE_TIMEOUT_SECONDS.
    PARSE_RANGE_PAGES: int = 25
    PARSE_WINDOW: int = 4
    URL_FETCH_TIMEOUT_SECONDS: int = 30 * 60
    # RustFS/S3: connecting, and waiting for the next bytes of a transfer.
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # ZIP import (#223): what an archive may expand to - unset, no limit. Over ZIP_IMPORT_MAX_FILES
    # files or ZIP_IMPORT_MAX_TOTAL_BYTES once decompressed, the whole archive is refused; a single
    # file over ZIP_IMPORT_MAX_FILE_BYTES, compressed more than ZIP_IMPORT_MAX_RATIO times, or more
    # than ZIP_IMPORT_MAX_DEPTH folders deep is skipped and listed in the summary. Only the ratio is set
    # by default: it is what stops a zip bomb, and a real file is never compressed that much.
    ZIP_IMPORT_MAX_FILES: int | None = None
    ZIP_IMPORT_MAX_TOTAL_BYTES: int | None = None
    ZIP_IMPORT_MAX_FILE_BYTES: int | None = None
    ZIP_IMPORT_MAX_RATIO: int | None = 100
    ZIP_IMPORT_MAX_DEPTH: int | None = None
    TESSDATA_PATH: str | None = None

    # The scheduled refresh of URL documents (#19): the minutes of each hour the beat (run inside each
    # worker, see the Dockerfile's `-B`) looks for documents due for one - on the hour and at half
    # past, the times a schedule can be set to. Several replicas each running their own beat is
    # harmless: the backend hands each due document to one scan only.
    URL_REFRESH_SCAN_MINUTES: str = "0,30"

    # Logging (#305): stdout - JSON for kubectl/Loki, or readable - from LOG_LEVEL up. The lines a task
    # logs from TASK_LOG_LEVEL up are also sent to the backend, to be followed in Muffin as it runs.
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"
    TASK_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
