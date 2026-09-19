"""Retrieval metrics computed from a ranked list of binary relevance judgments.

A QaPair only ever points at a source *document* (app/models/qa.py on the backend has no
chunk-level ground truth), so "relevant" here means "belongs to the QA pair's source document" -
the best proxy available without hand-annotated chunk relevance. `total_relevant` is every chunk
of that document (see BackendClient.get_document_chunk_count), not just the ones retrieved.
"""

import math


def precision_at_k(relevances: list[bool]) -> float:
    """Of what was actually retrieved, how much of it was relevant."""
    if not relevances:
        return 0.0
    return sum(relevances) / len(relevances)


def recall_at_k(relevances: list[bool], total_relevant: int) -> float:
    """Of everything relevant that exists, how much of it was retrieved - capped at 1.0 since
    `total_relevant` is a document-level proxy, not an exact top-k-shaped ground truth set."""
    if total_relevant <= 0:
        return 0.0
    return min(1.0, sum(relevances) / total_relevant)


def reciprocal_rank(relevances: list[bool]) -> float:
    """1 / (rank of the first relevant result), 0 if none of the retrieved results are relevant."""
    for rank, relevant in enumerate(relevances, start=1):
        if relevant:
            return 1.0 / rank
    return 0.0


def ndcg(relevances: list[bool]) -> float:
    """Normalized Discounted Cumulative Gain over binary relevance - rewards a relevant result
    appearing early, not just anywhere in the ranked list."""
    if not relevances:
        return 0.0
    dcg = sum((1.0 if relevant else 0.0) / math.log2(rank + 1) for rank, relevant in enumerate(relevances, start=1))
    ideal = sorted(relevances, reverse=True)
    idcg = sum((1.0 if relevant else 0.0) / math.log2(rank + 1) for rank, relevant in enumerate(ideal, start=1))
    return dcg / idcg if idcg > 0 else 0.0
