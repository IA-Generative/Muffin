import json
from typing import Any

from loguru import logger

from app.backend_client import backend_client


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:] if lines else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def default_model() -> str | None:
    return backend_client.get_default_chat_model()


def json_chat(model: str, system_prompt: str, user_content: str, *, fallback: Any) -> Any:
    """Chat call whose response is expected to be a single JSON value. Never lets a malformed
    or refused LLM response take the graph down - callers get `fallback` and log instead, since
    a routing/planning node choosing a safe default beats crashing the run."""
    try:
        raw = backend_client.llm_chat(
            model, [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        )
        return json.loads(strip_code_fence(raw))
    except Exception:
        logger.exception("LLM JSON call failed, falling back to default")
        return fallback
