import hashlib
import json
from typing import Any

from loguru import logger

from app import metrics
from app.backend_client import backend_client
from app.celery_app import celery_app
from app.config import settings
from app.task_logging import capture_task_logs

_ANSWER_SYSTEM_PROMPT = (
    "Answer the question using only the excerpts given below. If the excerpts don't contain "
    "enough information to answer, say so plainly rather than guessing."
)

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


_FALLBACK_JUDGMENT: dict[str, Any] = {
    "coherent": True,
    "coherence_issues": [],
    "context_usage_score": 1.0,
    "context_usage_issues": [],
    "reasoning": "The model's response could not be parsed as a judgment - defaulting to no "
    "issues found rather than reporting a fabricated problem.",
}


def _judge_discussion(model: str, transcript: str) -> dict[str, Any]:
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
        judgment = json.loads(_strip_code_fence(raw))
        if not isinstance(judgment, dict) or "coherent" not in judgment or "context_usage_score" not in judgment:
            raise ValueError(f"Expected a judgment object, got: {judgment!r}")
        return judgment
    except Exception:
        logger.exception("Discussion judgment call failed, falling back to a conservative default")
        return _FALLBACK_JUDGMENT


def _build_answer(model: str, question: str, search_results: list[dict[str, Any]]) -> str:
    if not search_results:
        return "No relevant excerpts were retrieved for this question."
    excerpts = "\n\n".join(f"[{i + 1}] {r['text']}" for i, r in enumerate(search_results))
    return backend_client.llm_chat(
        model,
        [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\n\nExcerpts:\n{excerpts}",
            },
        ],
    )


def _evaluation_hash(
    qa_pairs: list[dict[str, Any]],
    collection_settings: dict[str, Any],
    k: int,
    llm_model: str,
    validated_only: bool = False,
) -> str:
    """SHA-256 of everything that affects an evaluation run's result: the QA pairs (id, question,
    answer, document_id, validated), the chunking/embedding config, k, the LLM model, and the
    validated_only scope. If none of these changed since the last run with the same model, the
    result would be identical and there's no reason to re-run (same dedup strategy as
    _transcript_hash for DiscussionScore).
    """
    pairs_fingerprint = [
        {
            "id": p["id"],
            "question": p["question"],
            "answer": p["answer"],
            "document_id": str(p["document_id"]) if p.get("document_id") else None,
            "validated": p["validated"],
        }
        for p in sorted(qa_pairs, key=lambda p: p["id"])
    ]
    payload = {
        "qa_pairs": pairs_fingerprint,
        "chunking_strategy": collection_settings["chunking_strategy"],
        "chunk_size": collection_settings["chunk_size"],
        "chunk_overlap": collection_settings["chunk_overlap"],
        "embedding_model": collection_settings["embedding_model"],
        "k": k,
        "llm_model": llm_model,
        "validated_only": validated_only,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _score_pair(pair: dict[str, Any], search_results: list[dict[str, Any]], total_relevant: int) -> dict[str, float]:
    relevances = [result["document_id"] == pair["document_id"] for result in search_results]
    return {
        "precision_at_k": metrics.precision_at_k(relevances),
        "recall_at_k": metrics.recall_at_k(relevances, total_relevant),
        "reciprocal_rank": metrics.reciprocal_rank(relevances),
        "ndcg": metrics.ndcg(relevances),
    }


def _average(results: list[dict[str, Any]]) -> dict[str, float]:
    """The global aggregate - every evaluated pair, validated and not."""
    count = len(results)
    return {
        "precision_at_k": sum(r["precision_at_k"] for r in results) / count,
        "recall_at_k": sum(r["recall_at_k"] for r in results) / count,
        "mrr": sum(r["reciprocal_rank"] for r in results) / count,
        "ndcg": sum(r["ndcg"] for r in results) / count,
    }


def _subset_average(results: list[dict[str, Any]], validated: bool) -> dict[str, Any]:
    """Same four metrics as _average, but over just the validated (or just the not-yet-validated)
    subset - None when that subset is empty, so an absent subset never gets reported as a
    misleading 0.0 (see EvaluationRun's docstring on the backend)."""
    prefix = "validated" if validated else "unvalidated"
    subset = [r for r in results if r["validated"] is validated]
    if not subset:
        return {
            f"{prefix}_pair_count": 0,
            f"{prefix}_precision_at_k": None,
            f"{prefix}_recall_at_k": None,
            f"{prefix}_mrr": None,
            f"{prefix}_ndcg": None,
        }
    return {
        f"{prefix}_pair_count": len(subset),
        f"{prefix}_precision_at_k": sum(r["precision_at_k"] for r in subset) / len(subset),
        f"{prefix}_recall_at_k": sum(r["recall_at_k"] for r in subset) / len(subset),
        f"{prefix}_mrr": sum(r["reciprocal_rank"] for r in subset) / len(subset),
        f"{prefix}_ndcg": sum(r["ndcg"] for r in subset) / len(subset),
    }


@celery_app.task(name="app.tasks.run_evaluation", bind=True)
def run_evaluation(self, collection_id: str, k: int | None = None, validated_only: bool = False) -> None:
    """Replays every QA pair of a collection through the same search the research agent uses,
    scores retrieval against each pair's source document (the only ground truth a QaPair carries
    - see app/metrics.py), generates an answer from what was retrieved, then posts one
    fully-computed EvaluationRun back to the backend (see #11 - the model has no in-progress
    state, so nothing is created until everything is scored). The run's aggregates are reported
    three ways - global, validated-only, unvalidated-only - so a low score can be told apart from
    "these questions were never reviewed" rather than looking like a retrieval problem. When
    validated_only is True, only validated QA pairs are evaluated; when False (default), all QA
    pairs with a source document are evaluated regardless of validation status. No self.request.id
    Task registration here, unlike worker/document_process's spawned tasks: this is a single task
    with no children, and the backend already creates its Task row itself right after dispatching
    it (see EvaluationService.trigger - it already knows the user at that point, no round trip
    needed)."""
    with capture_task_logs(self.request.id):
        k = k or settings.DEFAULT_TOP_K
        collection_settings = backend_client.get_collection_settings(collection_id)
        model = (collection_settings.get("generation_models") or {}).get(
            "evaluation"
        ) or backend_client.get_default_chat_model()
        if model is None:
            logger.warning(f"No chat model available to run evaluation for collection {collection_id}, skipping")
            return

        qa_pairs = backend_client.list_qa_pairs(collection_id)
        # Relevance can only be judged at document granularity (see app/metrics.py's module
        # docstring) - a pair with no source document has nothing to score retrieval against,
        # regardless of whether it's validated.
        evaluable_pairs = [pair for pair in qa_pairs if pair.get("document_id")]
        # When validated_only is True, restrict to validated pairs only; when False (default),
        # evaluate all pairs with a source document - the run's validated/unvalidated breakdown
        # still separates them in the results.
        if validated_only:
            evaluable_pairs = [pair for pair in evaluable_pairs if pair.get("validated")]
        skipped = len(qa_pairs) - len(evaluable_pairs)
        if skipped:
            logger.info(f"Skipping {skipped} QA pair(s) with no source document")
        if not evaluable_pairs:
            logger.warning(f"No evaluable QA pairs for collection {collection_id}, nothing to run")
            return

        # Dedup: if an identical run already exists (same QA pairs content, same chunking/embedding
        # settings, same k, same LLM model, same validated_only scope), skip - the result would be
        # identical. Same strategy as score_discussion's content_hash skip (see #31).
        content_hash = _evaluation_hash(qa_pairs, collection_settings, k, model, validated_only)
        existing_id = backend_client.find_evaluation_run(collection_id, content_hash, model)
        if existing_id is not None:
            logger.info(
                f"Evaluation run {existing_id} already exists for collection {collection_id} "
                f"with the same content hash and model, skipping"
            )
            return

        logger.info(f"Evaluating {len(evaluable_pairs)} QA pair(s) for collection {collection_id} at k={k}")

        chunk_counts: dict[str, int] = {}
        results = []
        for pair in evaluable_pairs:
            document_id = pair["document_id"]
            search_results = backend_client.search([collection_id], pair["question"], k)
            if document_id not in chunk_counts:
                chunk_counts[document_id] = backend_client.get_document_chunk_count(document_id)

            scores = _score_pair(pair, search_results, chunk_counts[document_id])
            generated_answer = _build_answer(model, pair["question"], search_results)

            results.append(
                {
                    "qa_pair_id": pair["id"],
                    "question": pair["question"],
                    "expected_answer": pair["answer"],
                    "generated_answer": generated_answer,
                    "validated": pair["validated"],
                    "retrieved_sources": [f"{r['document_name']}#{r['chunk_id']}" for r in search_results],
                    **scores,
                }
            )

        payload = {
            "k": k,
            "pair_count": len(results),
            "llm_model": model,
            "snapshot_chunking_strategy": collection_settings["chunking_strategy"],
            "snapshot_chunk_size": collection_settings["chunk_size"],
            "snapshot_chunk_overlap": collection_settings["chunk_overlap"],
            "snapshot_embedding_model": collection_settings["embedding_model"],
            **_average(results),
            **_subset_average(results, validated=True),
            **_subset_average(results, validated=False),
            "content_hash": content_hash,
            "results": results,
        }
        run_id = backend_client.create_evaluation_run(collection_id, payload)
        logger.info(f"Evaluation run {run_id} created for collection {collection_id}: {len(results)} pair(s) scored")


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
    with capture_task_logs(self.request.id):
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
            "coherent": bool(judgment["coherent"]),
            "coherence_issues": judgment.get("coherence_issues", []),
            "context_usage_score": float(judgment["context_usage_score"]),
            "context_usage_issues": judgment.get("context_usage_issues", []),
            "reasoning": judgment.get("reasoning"),
        }
        score_id = backend_client.create_discussion_score(conversation_id, payload)
        logger.info(f"Discussion score {score_id} created for conversation {conversation_id}")
