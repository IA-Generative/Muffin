import hashlib
import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.backend_client import backend_client
from app.celery_app import celery_app

# At least 2 assistant turns are needed for "do these answers contradict each other" to mean
# anything - a single-turn conversation has nothing to compare across (see #31).
_MIN_ASSISTANT_TURNS_FOR_DISCUSSION_SCORE = 2

_DISCUSSION_SYSTEM_PROMPT = (
    "You are judging the quality of a multi-turn conversation between a user and an AI assistant "
    "that answers questions using a knowledge base. Judge two things, independently:\n"
    "1. Coherence: do the assistant's answers contradict each other across turns? List any "
    "specific contradictions found, quoting or paraphrasing the conflicting statements.\n"
    "2. Context usage: when a question depends on earlier conversation context (a pronoun, or an "
    "implicit reference to something discussed before), did the assistant correctly resolve and "
    "use that context rather than answering as if the question were asked in isolation? Score "
    "this from 0.0 (never handled correctly) to 1.0 (always handled correctly), and list any "
    "turns where context was mishandled.\n"
    'Respond only with JSON: {"coherent": bool, "coherence_issues": [array of short strings, '
    'empty if none], "context_usage_score": number between 0.0 and 1.0, "context_usage_issues": '
    '[array of short strings, empty if none], "reasoning": short string summarizing the verdict}.'
)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:] if lines else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_transcript(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"{message['role'].capitalize()}: {message['content']}" for message in messages)


def _transcript_hash(messages: list[dict[str, Any]]) -> str:
    """SHA-256 of the transcript - role + content of every message, in order. This is what
    DiscussionScore.content_hash stores: re-scoring the exact same conversation with the same
    model is a no-op (the worker skips it), but a conversation that grows gets re-scored.
    """
    payload = json.dumps(
        [{"role": m["role"], "content": m["content"]} for m in messages],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiscussionJudgment(BaseModel):
    """The judge's verdict on a conversation - the shape _DISCUSSION_SYSTEM_PROMPT asks the model
    to return. Validated on the way in: the response is untrusted, and a malformed one must fall
    back rather than crash the task."""

    coherent: bool
    coherence_issues: list[str] = Field(default_factory=list)
    context_usage_score: float
    context_usage_issues: list[str] = Field(default_factory=list)
    reasoning: str | None = None


_FALLBACK_JUDGMENT = DiscussionJudgment(
    coherent=True,
    context_usage_score=1.0,
    reasoning="The model's response could not be parsed as a judgment - defaulting to no "
    "issues found rather than reporting a fabricated problem.",
)


def _judge_discussion(model: str, transcript: str) -> DiscussionJudgment:
    """Never lets a malformed or refused LLM response take the task down - same reasoning as
    worker/agent_execution's json_chat: a conservative fallback (no issues found) beats crashing,
    and beats fabricating a specific problem the model never actually reported."""
    try:
        raw = backend_client.llm_chat(
            model,
            [
                {"role": "system", "content": _DISCUSSION_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
        )
        return DiscussionJudgment.model_validate_json(_strip_code_fence(raw))
    except Exception:
        logger.exception("Discussion judgment call failed, falling back to a conservative default")
        return _FALLBACK_JUDGMENT


@celery_app.task(name="app.tasks.score_discussion", bind=True)
def score_discussion(self, conversation_id: str, model: str | None = None) -> None:
    """Judges a whole conversation - not any one answer - for cross-turn coherence and correct
    use of conversational context (see #31). A single LLM judgment call, not a search-heavy loop
    like run_evaluation, but shares its queue/service since neither needs its own. No
    self.request.id Task registration here either, same reasoning as run_evaluation: the backend
    already creates the Task row itself at dispatch time (see ConversationService.
    trigger_discussion_score).

    When `model` is None, the hub's default chat model is used. When set, that specific model is
    used - the (conversation, content_hash, model) unique index means re-scoring the same
    transcript with a different model creates a new score row instead of being a no-op.
    """
    messages = backend_client.list_conversation_messages(conversation_id)
    assistant_turns = sum(1 for message in messages if message["role"] == "assistant")
    if assistant_turns < _MIN_ASSISTANT_TURNS_FOR_DISCUSSION_SCORE:
        logger.warning(
            f"Conversation {conversation_id} has only {assistant_turns} assistant turn(s), "
            "nothing to compare across turns - skipping"
        )
        return

    if model is None:
        model = backend_client.get_default_chat_model()
    if model is None:
        logger.warning(f"No chat model available to score conversation {conversation_id}, skipping")
        return

    content_hash = _transcript_hash(messages)
    existing_id = backend_client.find_discussion_score(conversation_id, content_hash, model)
    if existing_id is not None:
        logger.info(
            f"Conversation {conversation_id} already scored with model {model} for this "
            f"transcript (score {existing_id}), skipping"
        )
        return

    logger.info(f"Scoring conversation {conversation_id}: {len(messages)} message(s), {assistant_turns} turn(s)")
    judgment = _judge_discussion(model, _build_transcript(messages))

    payload = {
        "message_count": len(messages),
        "llm_model": model,
        "content_hash": content_hash,
        "coherent": judgment.coherent,
        "coherence_issues": judgment.coherence_issues,
        "context_usage_score": judgment.context_usage_score,
        "context_usage_issues": judgment.context_usage_issues,
        "reasoning": judgment.reasoning,
    }
    score_id = backend_client.create_discussion_score(conversation_id, payload)
    logger.info(f"Discussion score {score_id} created for conversation {conversation_id}")
