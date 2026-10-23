"""Not computing twice what the pipeline computed for the same file (#300).

Before it computes a stage, the worker tells the backend the stage's *fingerprint*: a hash of the file
and of everything the stage depends on. If another document of the same file - in any collection -
completed the stage under the same fingerprint, the backend copies its results and the worker skips the
work (the OCR, the embeddings, the LLM calls); otherwise the worker computes the stage and says when it
is done, which makes it a source for the next document.

A stage's fingerprint holds what changes its result, and nothing else, so that a stage is reused as
often as it can be: the summary does not depend on the embedding model (the backend makes the summary's
vector again from its text when the models differ), the chunks do. It holds the model actually used - the
hub's first model when none is configured, which changes over time - never "the default".

Every call is an optimization: any failure here means the stage is computed, never that it fails."""

import hashlib
import json
import re
from importlib import metadata
from typing import Any

from loguru import logger

from app.config import settings as worker_settings
from app.tasks import _shared

# Bumped when the way a stage computes its result changes (the chunking, a prompt): what was computed
# before is no longer what would be computed now, and must not be copied.
FINGERPRINT_VERSION = 1

EXTRACTION = "extraction"
CHUNKS = "chunks"
SUMMARY = "summary"
QA = "qa"
ENTITIES = "entities"
TAGS = "tags"

_HASH = re.compile(r"^[0-9a-f]{64}$")


def valid_hash(content_hash: Any) -> str | None:
    """The file's hash, if it is one - a document the backend has no hash for yet gives None."""
    return content_hash if isinstance(content_hash, str) and _HASH.match(content_hash) else None


def _digest(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parser_version() -> str:
    try:
        return metadata.version("liteparse")
    except metadata.PackageNotFoundError:
        return "unknown"


def _base(stage: str, content_hash: str) -> dict[str, Any]:
    return {"version": FINGERPRINT_VERSION, "stage": stage, "file": content_hash}


def extraction(content_hash: str) -> str:
    return _digest(
        {
            **_base(EXTRACTION, content_hash),
            "ocr": worker_settings.OCR_LANGUAGE,
            "parser": _parser_version(),
            # A long PDF is parsed range by range, and what liteparse does across pages (repeated headers
            # and footers) sees one range: another range size can read the pages differently.
            "range": worker_settings.PARSE_RANGE_PAGES,
            # The pages carry their positioned text (#350): an extraction made before has none, and a document
            # extracted now must not be given pages without it.
            "layout": 1,
        }
    )


def _extraction_of(content_hash: str) -> str:
    # Every later stage starts from the same pages: it depends on how they were extracted.
    return extraction(content_hash)


def chunks(content_hash: str, collection_settings: dict[str, Any]) -> str:
    windows = _shared._windows(collection_settings)
    return _digest(
        {
            **_base(CHUNKS, content_hash),
            "extraction": _extraction_of(content_hash),
            "strategy": collection_settings["chunking_strategy"],
            "size": collection_settings["chunk_size"],
            "overlap": collection_settings["chunk_overlap"],
            "window": windows["chunking_window_pages"],
            "slide": windows["chunking_slide_pages"],
            # The vectors are part of this stage, and a vector is only valid in its own model's index.
            "embedding_model": collection_settings["embedding_model"],
            # Cut by a model, the chunks are that model's, under those instructions. Only then: the
            # fingerprints of the other strategies stay what they were.
            **(
                {
                    "model": _shared._model_for(collection_settings, "chunking"),
                    "instructions": collection_settings["instructions"].get("chunking", ""),
                }
                if collection_settings["chunking_strategy"] == "llm"
                else {}
            ),
        }
    )


def summary(content_hash: str, collection_settings: dict[str, Any], model: str) -> str:
    windows = _shared._windows(collection_settings)
    return _digest(
        {
            **_base(SUMMARY, content_hash),
            "extraction": _extraction_of(content_hash),
            "model": model,
            "instructions": collection_settings["instructions"].get("summary", ""),
            "pages_per_map": windows["summary_pages_per_map"],
        }
    )


def qa(content_hash: str, collection_settings: dict[str, Any], model: str) -> str:
    windows = _shared._windows(collection_settings)
    return _digest(
        {
            **_base(QA, content_hash),
            "extraction": _extraction_of(content_hash),
            "model": model,
            "instructions": collection_settings["instructions"].get("qa", ""),
            "window": windows["qa_window_pages"],
            "slide": windows["qa_slide_pages"],
            "questions": windows["qa_questions_per_window"],
        }
    )


def entities(content_hash: str, collection_settings: dict[str, Any], model: str) -> str:
    windows = _shared._windows(collection_settings)
    return _digest(
        {
            **_base(ENTITIES, content_hash),
            "extraction": _extraction_of(content_hash),
            "model": model,
            "instructions": collection_settings["instructions"].get("extraction", ""),
            "window": windows["extraction_window_pages"],
            "slide": windows["extraction_slide_pages"],
        }
    )


def tags(content_hash: str, collection_settings: dict[str, Any], summary_model: str, tagging_model: str) -> str:
    """The tags are read from the summary: they depend on everything the summary does."""
    return _digest(
        {
            **_base(TAGS, content_hash),
            "summary": summary(content_hash, collection_settings, summary_model),
            "model": tagging_model,
            "instructions": collection_settings["instructions"].get("tagging", ""),
        }
    )


def begin(
    document_id: str,
    stage: str,
    fingerprint: str | None,
    expected: list[str] | None = None,
    content_hash: str | None = None,
) -> bool:
    """True: the stage was copied from another document of the same file, there is nothing to compute."""
    if fingerprint is None:
        return False
    try:
        reused = _shared.backend_client.begin_stage(document_id, stage, fingerprint, expected or [], content_hash)
    except Exception:
        logger.exception(f"Could not look for results to reuse for the {stage} of document {document_id}")
        return False
    if reused is True:
        logger.info(f"The {stage} of document {document_id} is reused from the same file: not computed")
    return reused is True


def done(document_id: str, stage: str, key: str = "_") -> None:
    """The stage (or a piece of it) is computed: another document of the same file can reuse it."""
    try:
        _shared.backend_client.stage_done(document_id, stage, key)
    except Exception:
        logger.exception(f"Could not record the {stage} of document {document_id} as done")
