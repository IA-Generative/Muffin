import uuid
from typing import Any

from app.graph.state import Evidence


def normalize_results(task_id: str, retrieval_query: str, results: list[dict[str, Any]]) -> list[Evidence]:
    """Every search result keeps its provenance (§15) - vdb_id, source_id, the query that found
    it - so later citations trace back to a real document instead of an anonymous string.
    """
    return [
        Evidence(
            id=str(uuid.uuid4()),
            task_id=task_id,
            vdb_id=str(result["collection_id"]),
            source_id=str(result["document_id"]),
            content=result["text"],
            metadata={
                "document_name": result["document_name"],
                "chunk_id": str(result["chunk_id"]),
                "page_number": result.get("page_number"),
                "evidence_kind": "document",
            },
            relevance_score=result.get("rank"),
            retrieval_query=retrieval_query,
        )
        for result in results
    ]
