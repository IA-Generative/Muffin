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


def _build_answer(model: str, question: str, search_results: list[dict[str, Any]]) -> str:
    if not search_results:
        return "No relevant excerpts were retrieved for this question."
    excerpts = "\n\n".join(f"[{i + 1}] {r['text']}" for i, r in enumerate(search_results))
    return backend_client.llm_chat(
        model,
        [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nExcerpts:\n{excerpts}"},
        ],
    )


def _score_pair(pair: dict[str, Any], search_results: list[dict[str, Any]], total_relevant: int) -> dict[str, float]:
    relevances = [result["document_id"] == pair["document_id"] for result in search_results]
    return {
        "precision_at_k": metrics.precision_at_k(relevances),
        "recall_at_k": metrics.recall_at_k(relevances, total_relevant),
        "reciprocal_rank": metrics.reciprocal_rank(relevances),
        "ndcg": metrics.ndcg(relevances),
    }


def _average(results: list[dict[str, Any]]) -> dict[str, float]:
    count = len(results)
    return {
        "precision_at_k": sum(r["precision_at_k"] for r in results) / count,
        "recall_at_k": sum(r["recall_at_k"] for r in results) / count,
        "mrr": sum(r["reciprocal_rank"] for r in results) / count,
        "ndcg": sum(r["ndcg"] for r in results) / count,
    }


@celery_app.task(name="app.tasks.run_evaluation", bind=True)
def run_evaluation(self, collection_id: str, k: int | None = None) -> None:
    """Replays every validated QA pair of a collection through the same search the research agent
    uses, scores retrieval against the pair's source document (the only ground truth a QaPair
    carries - see app/metrics.py), generates an answer from what was retrieved, then posts one
    fully-computed EvaluationRun back to the backend (see #11 - the model has no in-progress
    state, so nothing is created until everything is scored). No self.request.id Task
    registration here, unlike worker/document_process's spawned tasks: this is a single task with
    no children, and the backend already creates its Task row itself right after dispatching it
    (see EvaluationService.trigger - it already knows the user at that point, no round trip
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

        qa_pairs = backend_client.list_validated_qa_pairs(collection_id)
        # Relevance can only be judged at document granularity (see app/metrics.py's module
        # docstring) - a pair with no source document has nothing to score retrieval against.
        evaluable_pairs = [pair for pair in qa_pairs if pair.get("document_id")]
        skipped = len(qa_pairs) - len(evaluable_pairs)
        if skipped:
            logger.info(f"Skipping {skipped} validated QA pair(s) with no source document")
        if not evaluable_pairs:
            logger.warning(f"No evaluable QA pairs for collection {collection_id}, nothing to run")
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
            "results": results,
        }
        run_id = backend_client.create_evaluation_run(collection_id, payload)
        logger.info(f"Evaluation run {run_id} created for collection {collection_id}: {len(results)} pair(s) scored")
