"""Not computing twice what the pipeline computed for the same file (#300): the worker's side."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import reuse, task_logging, tasks
from app.scraping import FetchedUrl

FILE = "a" * 64
OTHER_FILE = "b" * 64


def _settings(**changes):
    base = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "embedder",
        "instructions": {"summary": "", "qa": "", "extraction": "", "tagging": ""},
        "generation_models": {"summary": "chat", "qa": "chat", "extraction": "chat", "tagging": "chat"},
        "pipeline_windows": {},
    }
    return {**base, **changes}


# -- the fingerprints -----------------------------------------------------------------------------


def test_a_fingerprint_is_stable_and_depends_on_the_file():
    assert reuse.extraction(FILE) == reuse.extraction(FILE) != reuse.extraction(OTHER_FILE)
    assert reuse.chunks(FILE, _settings()) == reuse.chunks(FILE, _settings())
    assert reuse.chunks(FILE, _settings()) != reuse.chunks(OTHER_FILE, _settings())


@pytest.mark.parametrize(
    "stage, changes",
    [
        ("chunks", {"chunking_strategy": "sentence"}),
        ("chunks", {"chunk_size": 800}),
        ("chunks", {"chunk_overlap": 0}),
        ("chunks", {"embedding_model": "another-embedder"}),
        ("chunks", {"pipeline_windows": {"chunking_window_pages": 5}}),
        ("summary", {"instructions": {"summary": "En 3 puces."}}),
        ("summary", {"pipeline_windows": {"summary_pages_per_map": 9}}),
        ("qa", {"instructions": {"qa": "Questions courtes."}}),
        ("qa", {"pipeline_windows": {"qa_questions_per_window": 7}}),
        ("qa", {"pipeline_windows": {"qa_window_pages": 4}}),
        ("entities", {"instructions": {"extraction": "Seulement les lieux."}}),
        ("entities", {"pipeline_windows": {"extraction_window_pages": 8}}),
        ("tags", {"instructions": {"tagging": "Trois tags."}}),
        ("tags", {"instructions": {"summary": "En 3 puces."}}),
    ],
)
def test_a_stage_changes_with_each_setting_it_depends_on(stage, changes):
    def fingerprint(settings):
        return {
            "chunks": lambda: reuse.chunks(FILE, settings),
            "summary": lambda: reuse.summary(FILE, settings, "chat"),
            "qa": lambda: reuse.qa(FILE, settings, "chat"),
            "entities": lambda: reuse.entities(FILE, settings, "chat"),
            "tags": lambda: reuse.tags(FILE, settings, "chat", "chat"),
        }[stage]()

    changed = {
        **_settings(),
        **{
            key: {**_settings().get(key, {}), **value} if isinstance(value, dict) else value
            for key, value in changes.items()
        },
    }

    assert fingerprint(changed) != fingerprint(_settings())


def test_the_model_actually_used_is_part_of_a_stage():
    assert reuse.summary(FILE, _settings(), "chat") != reuse.summary(FILE, _settings(), "another-chat")
    assert reuse.qa(FILE, _settings(), "chat") != reuse.qa(FILE, _settings(), "another-chat")
    assert reuse.entities(FILE, _settings(), "chat") != reuse.entities(FILE, _settings(), "another-chat")
    assert reuse.tags(FILE, _settings(), "chat", "t1") != reuse.tags(FILE, _settings(), "chat", "t2")
    # Tags are read from the summary: another summary model is other tags.
    assert reuse.tags(FILE, _settings(), "s1", "t") != reuse.tags(FILE, _settings(), "s2", "t")


def test_the_embedding_model_does_not_change_what_the_model_wrote():
    """The summary, the pairs and the entities are texts: a collection with another embedding model reuses
    them, and has the vectors made again (the backend does)."""
    other = _settings(embedding_model="another-embedder")

    assert reuse.summary(FILE, _settings(), "chat") == reuse.summary(FILE, other, "chat")
    assert reuse.qa(FILE, _settings(), "chat") == reuse.qa(FILE, other, "chat")
    assert reuse.entities(FILE, _settings(), "chat") == reuse.entities(FILE, other, "chat")
    assert reuse.tags(FILE, _settings(), "chat", "chat") == reuse.tags(FILE, other, "chat", "chat")


def test_the_stages_have_fingerprints_of_their_own():
    settings = _settings()
    fingerprints = {
        reuse.extraction(FILE),
        reuse.chunks(FILE, settings),
        reuse.summary(FILE, settings, "chat"),
        reuse.qa(FILE, settings, "chat"),
        reuse.entities(FILE, settings, "chat"),
        reuse.tags(FILE, settings, "chat", "chat"),
    }
    assert len(fingerprints) == 6


def test_a_new_version_of_the_pipeline_does_not_reuse_what_the_old_one_computed(monkeypatch):
    before = reuse.chunks(FILE, _settings())

    monkeypatch.setattr(reuse, "FINGERPRINT_VERSION", reuse.FINGERPRINT_VERSION + 1)

    assert reuse.chunks(FILE, _settings()) != before


def test_only_a_sha256_is_a_hash_of_a_file():
    assert reuse.valid_hash(FILE) == FILE
    for not_a_hash in (None, "", "abc", "A" * 64, MagicMock(), 12):
        assert reuse.valid_hash(not_a_hash) is None


# -- asking the backend ----------------------------------------------------------------------------


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    fake.begin_stage.return_value = False
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    monkeypatch.setattr(tasks._shared, "storage", MagicMock())
    fake.get_collection_settings.return_value = _settings()
    return fake


def test_a_failing_lookup_means_the_stage_is_computed_not_that_the_task_fails(backend):
    backend.begin_stage.side_effect = RuntimeError("backend down")

    assert reuse.begin("doc-1", reuse.CHUNKS, "fingerprint") is False


def test_a_stage_with_no_fingerprint_is_never_looked_up(backend):
    assert reuse.begin("doc-1", reuse.CHUNKS, None) is False
    backend.begin_stage.assert_not_called()


def test_only_a_clear_yes_is_a_reuse(backend):
    backend.begin_stage.return_value = MagicMock()  # truthy, but not an answer

    assert reuse.begin("doc-1", reuse.CHUNKS, "fingerprint") is False


def test_a_failure_to_record_a_stage_as_done_is_not_a_failure(backend):
    backend.stage_done.side_effect = RuntimeError("backend down")

    reuse.done("doc-1", reuse.CHUNKS)  # does not raise


# -- the extraction -------------------------------------------------------------------------------


def _file_document(**fields):
    return {
        "id": "doc-1",
        "type": "file",
        "name": "report.pdf",
        "storage_key": "k",
        "collection_id": "col-1",
        "content_hash": FILE,
        **fields,
    }


def test_a_file_whose_pages_exist_for_the_same_file_is_not_downloaded_nor_parsed(backend, monkeypatch):
    backend.get_document.return_value = _file_document()
    backend.begin_stage.return_value = True
    parse = MagicMock()
    monkeypatch.setattr(tasks._shared, "parse_file", parse)

    tasks.process_document("doc-1")

    backend.begin_stage.assert_called_once_with("doc-1", "extraction", reuse.extraction(FILE), [], FILE)
    tasks._shared.storage.get_object.assert_not_called()
    parse.assert_not_called()
    backend.add_page.assert_not_called()
    # The pipeline goes on: the chunks are next.
    backend.update_status.assert_any_call("doc-1", status="indexing", progress=50)
    assert tasks._shared._spawn.call_args.args[2] == "app.tasks.chunk_document"


def test_a_file_that_is_computed_is_announced_then_recorded_as_done(backend, monkeypatch):
    backend.get_document.return_value = _file_document()
    tasks._shared.storage.get_object.return_value = b"pdf"
    pages = [SimpleNamespace(page_num=1, text="page", blocks=[])]
    monkeypatch.setattr(tasks._shared, "parse_file", lambda data: SimpleNamespace(pages=pages, screenshots=[]))

    tasks.process_document("doc-1")

    names = [call[0] for call in backend.method_calls if call[0] in ("begin_stage", "add_page", "stage_done")]
    assert names == ["begin_stage", "add_page", "stage_done"]
    backend.stage_done.assert_called_once_with("doc-1", "extraction", "_")


def test_a_file_with_no_hash_yet_is_hashed_from_its_bytes_before_the_lookup(backend, monkeypatch):
    """Uploaded before hashes were kept, or its file was replaced: hashed here, from the bytes about to be
    parsed anyway - downloaded once."""
    import hashlib

    backend.get_document.return_value = _file_document(content_hash=None)
    tasks._shared.storage.get_object.return_value = b"pdf-bytes"
    pages = [SimpleNamespace(page_num=1, text="page", blocks=[])]
    monkeypatch.setattr(tasks._shared, "parse_file", lambda data: SimpleNamespace(pages=pages, screenshots=[]))

    tasks.process_document("doc-1")

    digest = hashlib.sha256(b"pdf-bytes").hexdigest()
    backend.begin_stage.assert_called_once_with("doc-1", "extraction", reuse.extraction(digest), [], digest)
    tasks._shared.storage.get_object.assert_called_once_with("k")


def test_an_html_page_is_looked_up_by_the_hash_of_its_text(backend, monkeypatch):
    backend.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com",
        "storage_key": None,
        "collection_id": "col-1",
    }
    page = FetchedUrl(markdown="# Page")
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: page)

    tasks.process_document("doc-1")

    backend.begin_stage.assert_called_once_with(
        "doc-1", "extraction", reuse.extraction(page.content_hash), [], page.content_hash
    )
    backend.add_page.assert_called_once()


def test_a_reused_html_page_is_not_written_again_but_the_hash_of_the_refresh_is_still_recorded(backend, monkeypatch):
    backend.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com",
        "storage_key": None,
        "collection_id": "col-1",
    }
    backend.begin_stage.return_value = True
    page = FetchedUrl(markdown="# Page")
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: page)

    tasks.process_document("doc-1")

    backend.add_page.assert_not_called()
    backend.set_content_hash.assert_called_once_with("doc-1", page.content_hash)


def test_the_file_a_url_served_is_looked_up_by_the_hash_of_its_bytes(backend, monkeypatch):
    backend.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com/r.pdf",
        "storage_key": None,
        "collection_id": "col-1",
    }
    served = FetchedUrl(data=b"%PDF", filename="r.pdf", content_type="application/pdf")
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: served)
    backend.begin_stage.return_value = True

    tasks.process_document("doc-1")

    backend.begin_stage.assert_called_once_with(
        "doc-1", "extraction", reuse.extraction(served.content_hash), [], served.content_hash
    )
    tasks._shared.storage.get_object.assert_not_called()


def test_a_tabular_file_is_not_looked_up(backend):
    backend.get_document.return_value = _file_document(name="table.csv")

    tasks.process_document("doc-1")

    backend.begin_stage.assert_not_called()
    assert tasks._shared._spawn.call_args.args[2] == "app.tasks.process_tabular_document"


# -- the chunks, the QA pairs and the entities ------------------------------------------------------


def _chunking(backend, pages=3, **document):
    backend.get_document.return_value = _file_document(**document)
    backend.get_pages.return_value = [{"page_number": n, "content": f"Page {n}.\n\nMore."} for n in range(1, pages + 1)]


def _spawned(backend):
    return [call.args[2] for call in tasks._shared._spawn.call_args_list]


def test_chunks_that_exist_for_the_same_file_are_neither_cut_nor_embedded(backend):
    _chunking(backend)
    backend.begin_stage.side_effect = lambda document_id, stage, *args: stage == "chunks"

    tasks.chunk_document("doc-1", "col-1")

    backend.embed.assert_not_called()
    backend.add_chunk.assert_not_called()
    backend.prune_chunks.assert_not_called()
    # The document is indexed all the same, and the rest of the pipeline goes on.
    backend.update_status.assert_any_call("doc-1", status="indexed", progress=100)
    assert "app.tasks.summarize_document" in _spawned(backend)


def test_chunks_that_are_computed_are_recorded_as_done_once_written(backend):
    _chunking(backend)

    tasks.chunk_document("doc-1", "col-1")

    names = [call[0] for call in backend.method_calls if call[0] in ("add_chunk", "prune_chunks", "stage_done")]
    assert names[-2:] == ["prune_chunks", "stage_done"]
    assert ("doc-1", "chunks", "_") in [call.args for call in backend.stage_done.call_args_list]


def test_the_windows_are_announced_so_that_the_stage_completes_when_each_is_written(backend):
    _chunking(backend, pages=3)

    tasks.chunk_document("doc-1", "col-1")

    announced = {call.args[1]: call.args[3] for call in backend.begin_stage.call_args_list}
    # 3 pages: windows of 2 pages for the pairs, of 4 for the entities, each sliding by 1 (the defaults).
    # The keys are the ones the window tasks write with, which is what completes the stage.
    assert announced["qa"] == ["window:1-2", "window:2-3"]
    assert announced["entities"] == ["pages:1-3"]
    assert _spawned(backend).count("app.tasks.generate_qa_window") == 2


def test_pairs_that_exist_for_the_same_file_spawn_no_window(backend):
    _chunking(backend)
    backend.begin_stage.side_effect = lambda document_id, stage, *args: stage == "qa"

    tasks.chunk_document("doc-1", "col-1")

    assert "app.tasks.generate_qa_window" not in _spawned(backend)
    assert "app.tasks.extract_entities_window" in _spawned(backend)


def test_entities_that_exist_for_the_same_file_spawn_no_window(backend):
    _chunking(backend)
    backend.begin_stage.side_effect = lambda document_id, stage, *args: stage == "entities"

    tasks.chunk_document("doc-1", "col-1")

    assert "app.tasks.extract_entities_window" not in _spawned(backend)
    assert "app.tasks.generate_qa_window" in _spawned(backend)


def test_a_document_with_no_hash_is_computed_whole(backend):
    _chunking(backend, content_hash=None)

    tasks.chunk_document("doc-1", "col-1")

    backend.begin_stage.assert_not_called()
    assert "app.tasks.generate_qa_window" in _spawned(backend)


def test_no_model_for_a_step_means_nothing_to_reuse(backend):
    _chunking(backend)
    backend.get_default_chat_model.return_value = None
    backend.get_collection_settings.return_value = _settings(generation_models={})

    tasks.chunk_document("doc-1", "col-1")

    assert {call.args[1] for call in backend.begin_stage.call_args_list} == {"chunks"}


def test_the_tabular_pipeline_looks_nothing_up(backend):
    _chunking(backend)

    tasks.chunk_document("doc-1", "col-1", skip_summary=True, skip_qa=True, skip_chunking=True, skip_extraction=True)

    backend.begin_stage.assert_not_called()


# -- the summary and the tags ---------------------------------------------------------------------


def test_a_summary_that_exists_for_the_same_file_is_not_generated_but_the_rest_goes_on(backend, monkeypatch):
    backend.get_document.return_value = _file_document()
    backend.get_pages.return_value = [{"page_number": 1, "content": "text"}]
    backend.begin_stage.return_value = True
    chat = MagicMock()
    monkeypatch.setattr(tasks._shared, "_chat", chat)

    tasks.summarize_document("doc-1", "col-1")

    chat.assert_not_called()
    backend.set_document_summary.assert_not_called()
    # The follow-ups are the collection's own, and run all the same.
    assert _spawned(backend) == [
        "app.tasks.tag_document",
        "app.tasks.update_collection_description",
        "app.tasks.update_collection_tags",
    ]
    backend.suggest_filing.assert_called_once_with("doc-1")


def test_a_summary_that_is_generated_is_recorded_as_done(backend, monkeypatch):
    backend.get_document.return_value = _file_document()
    backend.get_pages.return_value = [{"page_number": 1, "content": "text"}]
    monkeypatch.setattr(tasks._shared, "_chat", lambda model, system, content: "A summary.")

    tasks.summarize_document("doc-1", "col-1")

    backend.set_document_summary.assert_called_once()
    backend.stage_done.assert_called_once_with("doc-1", "summary", "_")


def test_tags_that_exist_for_the_same_file_and_settings_are_not_asked_again(backend, monkeypatch):
    backend.get_document.return_value = _file_document(summary="A summary.")
    backend.begin_stage.return_value = True
    chat = MagicMock()
    monkeypatch.setattr(tasks._shared, "_chat_json", chat)

    tasks.tag_document("doc-1", "col-1")

    chat.assert_not_called()
    backend.replace_document_tags.assert_not_called()


def test_tags_depend_on_the_summary_model_too(backend, monkeypatch):
    backend.get_document.return_value = _file_document(summary="A summary.")
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, system, content: ["legal"])

    tasks.tag_document("doc-1", "col-1")

    expected = reuse.tags(FILE, _settings(), "chat", "chat")
    backend.begin_stage.assert_called_once_with("doc-1", "tags", expected, [], None)
    backend.replace_document_tags.assert_called_once_with("doc-1", ["legal"])
    backend.stage_done.assert_called_once_with("doc-1", "tags", "_")


def test_the_pieces_announced_are_exactly_the_ones_the_window_tasks_write(backend, monkeypatch):
    """What completes a stage is each announced piece being written under its own key: a mismatch between
    the keys chunk_document announces and the ones the window tasks send would leave the stage incomplete
    forever, and never reusable."""
    _chunking(backend, pages=5)
    backend.embed.return_value = [0.1]
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: [] if "question" in prompt else {})
    tasks.chunk_document("doc-1", "col-1")
    announced = {call.args[1]: call.args[3] for call in backend.begin_stage.call_args_list}
    written = {"qa": [], "entities": []}

    for call in tasks._shared._spawn.call_args_list:
        name, args = call.args[2], call.args[1]
        if name == "app.tasks.generate_qa_window":
            tasks.generate_qa_window(*args)
            written["qa"].append(backend.replace_generated_qa.call_args.args[2])
        elif name == "app.tasks.extract_entities_window":
            tasks.extract_entities_window(*args)
            written["entities"].append(backend.replace_entity_window.call_args.args[1])

    assert written["qa"] == announced["qa"] and written["qa"]
    assert written["entities"] == announced["entities"] and written["entities"]
