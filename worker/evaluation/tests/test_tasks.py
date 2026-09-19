from unittest.mock import MagicMock

from app import task_logging, tasks


def _fake_settings(**overrides):
    settings = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "generation_models": {},
    }
    settings.update(overrides)
    return settings


def _qa_pair(id_: str, question: str, document_id: str | None, validated: bool):
    return {
        "id": id_,
        "question": question,
        "answer": "answer",
        "document_id": document_id,
        "validated": validated,
    }


def _search_result(document_id: str, document_name: str = "handbook.pdf", chunk_id: str = "chunk-1"):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": document_name,
        "collection_id": "col-1",
        "text": "Telework is allowed 2 days per week.",
        "rank": 1.0,
        "page_number": 1,
    }


def test_run_evaluation_scores_each_pair_and_posts_one_run(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "What is the telework policy?", "doc-1", validated=True)]
    fake.search.return_value = [
        _search_result("doc-1"),
        _search_result("doc-2", "other.pdf", "chunk-2"),
    ]
    fake.get_document_chunk_count.return_value = 4
    fake.llm_chat.return_value = "Telework is allowed 2 days per week."
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", 5)

    fake.search.assert_called_once_with(["col-1"], "What is the telework policy?", 5)
    fake.get_document_chunk_count.assert_called_once_with("doc-1")

    fake.create_evaluation_run.assert_called_once()
    collection_id, payload = fake.create_evaluation_run.call_args.args
    assert collection_id == "col-1"
    assert payload["pair_count"] == 1
    assert payload["k"] == 5
    assert payload["snapshot_chunking_strategy"] == "paragraph"
    assert payload["precision_at_k"] == 0.5  # 1 of 2 retrieved chunks belongs to doc-1
    result = payload["results"][0]
    assert result["qa_pair_id"] == "qa-1"
    assert result["validated"] is True
    assert result["generated_answer"] == "Telework is allowed 2 days per week."
    assert result["retrieved_sources"] == ["handbook.pdf#chunk-1", "other.pdf#chunk-2"]

    fake.set_task_logs.assert_called_once()


def test_run_evaluation_breaks_metrics_down_by_validated_status(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [
        _qa_pair("qa-validated", "Validated question?", "doc-1", validated=True),
        _qa_pair("qa-unvalidated", "Unvalidated question?", "doc-1", validated=False),
    ]
    # Perfect match for the validated pair, a miss for the unvalidated one - the two subset
    # averages must diverge to prove they're computed independently, not just copies of the
    # global one.
    fake.search.side_effect = [
        [_search_result("doc-1")],
        [_search_result("doc-2", "other.pdf", "chunk-2")],
    ]
    fake.get_document_chunk_count.return_value = 1
    fake.llm_chat.return_value = "answer"
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", 5)

    _, payload = fake.create_evaluation_run.call_args.args
    assert payload["pair_count"] == 2
    assert payload["validated_pair_count"] == 1
    assert payload["validated_precision_at_k"] == 1.0
    assert payload["unvalidated_pair_count"] == 1
    assert payload["unvalidated_precision_at_k"] == 0.0
    # Global sits between the two, over both pairs together.
    assert payload["precision_at_k"] == 0.5


def test_run_evaluation_reports_none_for_an_empty_subset(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    fake.search.return_value = []
    fake.get_document_chunk_count.return_value = 1
    fake.llm_chat.return_value = "answer"
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", 5)

    _, payload = fake.create_evaluation_run.call_args.args
    assert payload["validated_pair_count"] == 1
    assert payload["unvalidated_pair_count"] == 0
    assert payload["unvalidated_precision_at_k"] is None
    assert payload["unvalidated_recall_at_k"] is None
    assert payload["unvalidated_mrr"] is None
    assert payload["unvalidated_ndcg"] is None


def test_run_evaluation_skips_qa_pairs_with_no_source_document(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "Manual pair?", None, validated=True)]

    tasks.run_evaluation("col-1", 5)

    fake.search.assert_not_called()
    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_skips_entirely_without_a_chat_model(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = None

    tasks.run_evaluation("col-1", 5)

    fake.list_qa_pairs.assert_not_called()
    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_prefers_a_configured_evaluation_model(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings(generation_models={"evaluation": "gpt-configured"})
    fake.list_qa_pairs.return_value = []

    tasks.run_evaluation("col-1", 5)

    fake.get_default_chat_model.assert_not_called()


def test_run_evaluation_defaults_k_from_settings(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    monkeypatch.setattr(tasks.settings, "DEFAULT_TOP_K", 7)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    fake.search.return_value = []
    fake.get_document_chunk_count.return_value = 1
    fake.llm_chat.return_value = "answer"
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", None)

    fake.search.assert_called_once_with(["col-1"], "q", 7)
