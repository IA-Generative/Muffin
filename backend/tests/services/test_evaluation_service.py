"""The trigger-time dedup hash must equal the worker's: the backend answers "skipped" before
dispatching by computing the digest the worker's run_evaluation would compute over the same
collection state (worker/evaluation/app/tasks.py's EvaluationConfig.content_hash). Both sides pin the same
fixture digest here and in worker/evaluation/tests/test_tasks.py, so either drifting breaks
tests."""

from types import SimpleNamespace

from app.services.evaluation_service import _evaluation_hash

# Same fixture as worker/evaluation/tests/test_tasks.py's _VECTOR_* constants.
_VECTOR_PAIRS = [
    SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        question="Quelle est la réponse ?",
        answer="42",
        document_id="22222222-2222-2222-2222-222222222222",
        validated=True,
        golden=False,
        relevant_document_ids=[],
    ),
    SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333",
        question="Golden ?",
        answer="Oui.",
        document_id=None,
        validated=True,
        golden=True,
        relevant_document_ids=["44444444-4444-4444-4444-444444444444", "22222222-2222-2222-2222-222222222222"],
    ),
]
_VECTOR_SETTINGS = SimpleNamespace(
    chunking_strategy="paragraph",
    chunk_size=500,
    chunk_overlap=50,
    index_embedding_model=None,
    embedding_model="text-embedding-3-small",
)
_VECTOR_DIGEST = "d3e7f82d4a4799222175523743967e92b1d4dcddafec047443b3b2a4c32c28f0"


def test_evaluation_hash_matches_the_worker_vector():
    assert _evaluation_hash(_VECTOR_PAIRS, _VECTOR_SETTINGS, 5, "judge-model", "gen-model", False) == _VECTOR_DIGEST


def test_evaluation_hash_resolves_the_index_embedding_model():
    # The worker hashes the embedding model the internal settings endpoint resolved for it
    # (index_embedding_model takes precedence over embedding_model) - the backend must apply
    # the same resolution, not hash the raw column.
    overridden = SimpleNamespace(**{**_VECTOR_SETTINGS.__dict__, "index_embedding_model": "other-embedding"})
    assert _evaluation_hash(_VECTOR_PAIRS, overridden, 5, "judge-model", "gen-model", False) != _VECTOR_DIGEST
