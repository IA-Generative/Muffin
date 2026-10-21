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


# -- golden (test) pairs, scored apart (#260) ---------------------------------------------------


def _golden(id_: str, question: str, relevant: list[str]):
    return {
        "id": id_,
        "question": question,
        "answer": "answer",
        "document_id": relevant[0] if relevant else None,
        "validated": True,
        "golden": True,
        "relevant_document_ids": relevant,
    }


def _run(monkeypatch, pairs, search_results, chunk_counts=None):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = pairs
    fake.search.return_value = search_results
    fake.get_document_chunk_count.side_effect = lambda document_id: (chunk_counts or {}).get(document_id, 4)
    fake.llm_chat.return_value = "answer"
    fake.create_evaluation_run.return_value = "run-1"
    tasks.run_evaluation("col-1", 5)
    return fake, fake.create_evaluation_run.call_args.args[1]


def test_golden_pairs_are_scored_apart_from_the_others(monkeypatch):
    fake, payload = _run(
        monkeypatch,
        [
            _qa_pair("qa-1", "Generated, found?", "doc-1", validated=True),
            _golden("qa-2", "Golden, found?", ["doc-1"]),
        ],
        [_search_result("doc-1")],
    )

    # Every pair is evaluated and flagged...
    assert payload["pair_count"] == 2
    assert {r["qa_pair_id"]: r["golden"] for r in payload["results"]} == {"qa-1": False, "qa-2": True}
    # ...and the golden one has its own aggregate, left out of every other one.
    assert payload["golden_pair_count"] == 1
    assert payload["golden_precision_at_k"] == 1.0
    assert payload["validated_pair_count"] == 1 and payload["unvalidated_pair_count"] == 0


def test_a_golden_score_is_never_blended_with_the_generated_ones(monkeypatch):
    # The generated question finds its document, the golden one does not: neither score moves the other.
    def search(_collection_ids, question, _k):
        return [_search_result("doc-1")] if "Generated" in question else [_search_result("doc-9")]

    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [
        _qa_pair("qa-1", "Generated, found?", "doc-1", validated=True),
        _golden("qa-2", "Golden, not found", ["doc-1"]),
    ]
    fake.search.side_effect = search
    fake.get_document_chunk_count.return_value = 4
    fake.llm_chat.return_value = "answer"
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", 5)

    payload = fake.create_evaluation_run.call_args.args[1]
    assert payload["precision_at_k"] == 1.0 and payload["mrr"] == 1.0
    assert payload["validated_precision_at_k"] == 1.0
    assert payload["golden_precision_at_k"] == 0.0 and payload["golden_mrr"] == 0.0


def test_a_run_made_only_of_golden_pairs_has_no_global_aggregate(monkeypatch):
    _, payload = _run(monkeypatch, [_golden("qa-1", "Golden", ["doc-1"])], [_search_result("doc-1")])

    assert payload["precision_at_k"] is None and payload["mrr"] is None
    assert payload["validated_pair_count"] == 0 and payload["validated_precision_at_k"] is None
    assert payload["golden_pair_count"] == 1 and payload["golden_ndcg"] == 1.0


def test_a_run_without_golden_pairs_reports_none_for_them(monkeypatch):
    _, payload = _run(monkeypatch, [_qa_pair("qa-1", "Generated", "doc-1", validated=True)], [_search_result("doc-1")])

    assert payload["golden_pair_count"] == 0
    assert payload["golden_precision_at_k"] is None and payload["golden_recall_at_k"] is None


def test_a_golden_pair_with_several_relevant_documents_counts_them_all(monkeypatch):
    fake, payload = _run(
        monkeypatch,
        [_golden("qa-1", "Spans two documents", ["doc-1", "doc-2"])],
        [_search_result("doc-1"), _search_result("doc-2", "other.pdf", "chunk-2"), _search_result("doc-3", "x.pdf")],
        chunk_counts={"doc-1": 2, "doc-2": 2},
    )

    result = payload["results"][0]
    # Two of the three retrieved chunks are relevant; recall is over the chunks of both documents.
    assert result["precision_at_k"] == 2 / 3
    assert result["recall_at_k"] == 2 / 4
    assert {call.args[0] for call in fake.get_document_chunk_count.call_args_list} == {"doc-1", "doc-2"}


def test_a_golden_pair_without_any_document_cannot_be_scored(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.list_qa_pairs.return_value = [_golden("qa-1", "No document", [])]

    tasks.run_evaluation("col-1", 5)

    fake.create_evaluation_run.assert_not_called()


def test_adding_a_golden_pair_changes_the_evaluation_hash():
    settings = _fake_settings()
    generated = [_qa_pair("qa-1", "q", "doc-1", validated=True)]

    base = tasks._evaluation_hash(generated, settings, 5, "m")
    with_golden = tasks._evaluation_hash([*generated, _golden("qa-2", "q2", ["doc-1"])], settings, 5, "m")
    other_documents = tasks._evaluation_hash([*generated, _golden("qa-2", "q2", ["doc-1", "doc-2"])], settings, 5, "m")

    assert len({base, with_golden, other_documents}) == 3
