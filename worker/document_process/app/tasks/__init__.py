"""Package des tâches Celery du worker document_process.

Ce package remplace l'ancien module ``app/tasks.py`` (883 lignes) scindé en
sous-modules thématiques. L'``__init__`` ré-exporte tous les noms publics pour
préserver la compatibilité ascendante :

- ``from app import tasks; tasks.process_document(...)``  (celery_app.py)
- ``monkeypatch.setattr(tasks, "backend_client", ...)``    (tests)
- ``tasks._spawn(...)``, ``tasks._chat(...)``, etc.

Ordre d'import carefully choisi pour casser les dépendances circulaires :
``_shared`` → ``extract`` → ``qa`` → ``collection`` → ``summarize`` → ``chunk``
→ ``process``.
"""

# --- Shared utilities (constants + helpers) ---
# --- Re-exports used by tests via monkeypatch.setattr(tasks, ...) ---
# These are imported into process.py but tests patch them on the package
# level, so they must be accessible as tasks.fetch_url_markdown etc.
from app.celery_app import celery_app  # noqa: F401
from app.tasks._shared import (  # noqa: F401
    PIPELINE_WINDOW_DEFAULTS,
    TOKENS_PER_CHAR,
    _batches,
    _chat,
    _chat_json,
    _fail,
    _get_pages,
    _model_for,
    _spawn,
    _strip_code_fence,
    _window_text,
    _windows,
    backend_client,
    fetch_url_markdown,
    parse_file,
    storage,
)
from app.tasks.chunk import chunk_document  # noqa: F401
from app.tasks.collection import (  # noqa: F401
    update_collection_description,
    update_collection_tags,
)

# --- Task modules (order matters for circular imports) ---
from app.tasks.extract import extract_entities_window  # noqa: F401
from app.tasks.process import (  # noqa: F401
    _process_file,
    _process_url,
    process_document,
    process_tabular_document,
)
from app.tasks.qa import generate_collection_qa, generate_qa_window  # noqa: F401
from app.tasks.summarize import summarize_document, tag_document  # noqa: F401

__all__ = [
    # Constants
    "TOKENS_PER_CHAR",
    "PIPELINE_WINDOW_DEFAULTS",
    # Shared helpers
    "_strip_code_fence",
    "_windows",
    "_model_for",
    "_spawn",
    "_chat",
    "_chat_json",
    "_batches",
    "_window_text",
    "_get_pages",
    "_fail",
    # Tasks
    "process_document",
    "process_tabular_document",
    "chunk_document",
    "summarize_document",
    "tag_document",
    "generate_qa_window",
    "extract_entities_window",
    "update_collection_description",
    "update_collection_tags",
    "generate_collection_qa",
    # Internal helpers used by tests
    "_process_url",
    "_process_file",
    # Re-exported modules/objects
    "backend_client",
    "celery_app",
    "parse_file",
    "fetch_url_markdown",
    "storage",
]
