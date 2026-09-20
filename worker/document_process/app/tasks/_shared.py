"""Utilitaires partagés entre toutes les tâches Celery du worker.

Centralise les helpers LLM, le dispatch de sous-tâches, la gestion d'erreurs
et les constantes de pipeline. Chaque module de tâches importe depuis ici
pour éviter les dépendances circulaires entre modules de tâches.
"""

import json
from typing import Any

from loguru import logger

from app.backend_client import backend_client  # noqa: F401
from app.chunking import PageText
from app.parsing import parse_file  # noqa: F401
from app.scraping import fetch_url_markdown  # noqa: F401
from app.storage import storage  # noqa: F401

TOKENS_PER_CHAR = 0.25  # rough estimate, good enough until a real tokenizer is wired in

# Mirrors app/schemas/collection.py's PipelineWindowsOut defaults - the
# collection settings endpoint only returns the keys the user actually
# overrode, missing keys fall back to these.
PIPELINE_WINDOW_DEFAULTS = {
    "summary_pages_per_map": 5,
    "qa_window_pages": 2,
    "qa_slide_pages": 1,
    "qa_questions_per_window": 3,
    "extraction_window_pages": 4,
    "extraction_slide_pages": 1,
    "chunking_window_pages": 2,
    "chunking_slide_pages": 1,
    "collection_qa_count": 3,
}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:] if lines else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _windows(settings: dict[str, Any]) -> dict[str, int]:
    return {**PIPELINE_WINDOW_DEFAULTS, **(settings.get("pipeline_windows") or {})}


def _model_for(settings: dict[str, Any], step: str) -> str | None:
    """Falls back to the LLM hub's first available chat model when this step
    has none configured, so a fresh collection's pipeline works out of the
    box instead of silently skipping every generation step until someone
    visits Paramètres and saves a model for each one."""
    configured = (settings.get("generation_models") or {}).get(step)
    return configured or backend_client.get_default_chat_model()


def _spawn(task, args: list[Any], task_name: str, document_id: str, parent_task_id: str | None) -> None:
    result = task.apply_async(args=args)
    backend_client.create_task(result.id, task_name, document_id, parent_celery_task_id=parent_task_id)


def _chat(model: str, system: str, user_content: str) -> str:
    messages = (
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        if system
        else [{"role": "user", "content": user_content}]
    )
    return backend_client.llm_chat(model, messages)


def _chat_json(model: str, system: str, user_content: str) -> Any:
    raw = _chat(model, system, user_content)
    cleaned = _strip_code_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        logger.error(f"Model '{model}' returned invalid JSON ({len(raw)} chars, starts with: {raw[:200]!r})")
        raise ValueError(f"Model '{model}' returned invalid JSON") from error


def _batches(pages: list[PageText], size: int) -> list[list[PageText]]:
    size = max(size, 1)
    return [pages[i : i + size] for i in range(0, len(pages), size)]


def _window_text(pages: list[PageText], start_page: int, end_page: int) -> str:
    return "\n\n".join(page.content for page in pages if start_page <= page.page_number <= end_page)


def _get_pages(document_id: str) -> list[PageText]:
    return [PageText(page_number=p["page_number"], content=p["content"]) for p in backend_client.get_pages(document_id)]


def _fail(document_id: str, task_label: str, error: Exception) -> None:
    logger.exception(f"Failed to {task_label} for document {document_id}")
    try:
        backend_client.set_document_error(document_id, str(error))
    except Exception:
        logger.exception(f"Also failed to report the error for document {document_id} back to the backend")
