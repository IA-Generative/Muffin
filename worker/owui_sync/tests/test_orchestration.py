"""A synchronisation is phases of small tasks (#453): the fan-out, the isolation of an error, and the cleaning."""

from unittest.mock import MagicMock

import pytest

from app import tasks
from app.owui_client import OwuiFile, OwuiGroup, OwuiKnowledge


@pytest.fixture
def fan_out(monkeypatch):
    """What each phase starts: (tasks of the phase, the phase that follows)."""
    started = []
    monkeypatch.setattr(tasks, "_fan_out", lambda units, nxt: started.append((list(units), nxt)))
    return started


def _knowledge(knowledge_id: str) -> OwuiKnowledge:
    return OwuiKnowledge(id=knowledge_id, user_id="o", name=knowledge_id)


def test_the_root_starts_one_task_per_group_then_the_knowledge_bases(monkeypatch, fan_out):
    owui = MagicMock()
    owui.groups.return_value = [OwuiGroup(id="g1", name="A"), OwuiGroup(id="g2", name="B")]
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)

    result = tasks.sync_owui.run()

    [(units, nxt)] = fan_out
    assert [unit.args for unit in units] == [("g1",), ("g2",)]
    assert nxt.task == "app.tasks.sync_knowledge_bases"
    assert nxt.args[0]["group_ids"] == ["g1", "g2"]
    assert result["groups"] == 2


def test_a_group_that_failed_is_reported_and_does_not_stop_the_knowledge_bases(monkeypatch, fan_out):
    owui = MagicMock()
    owui.knowledge_bases.return_value = [_knowledge("kb1"), _knowledge("kb2")]
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
    run = {"id": "r"}

    tasks.sync_knowledge_bases.run([{"status": "error", "error": "boom", "object": "g1"}, {"id": "x"}], run)

    [(units, nxt)] = fan_out
    assert [unit.args for unit in units] == [("kb1",), ("kb2",)]
    assert nxt.task == "app.tasks.sync_files"
    assert [error["object"] for error in run["group_errors"]] == ["g1"]


def test_a_knowledge_base_that_failed_or_cannot_be_listed_is_left_out_of_the_cleaning(monkeypatch, fan_out):
    def files(knowledge_id):
        if knowledge_id == "kb3":
            raise RuntimeError("cannot list")
        return [OwuiFile(id=f"{knowledge_id}-f", filename="a")]

    owui = MagicMock()
    owui.knowledge_files.side_effect = files
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
    run = {"id": "r", "knowledge_ids": ["kb1", "kb2", "kb3"]}

    tasks.sync_files.run([{"status": "error", "error": "boom", "object": "kb2"}], run)

    [(units, nxt)] = fan_out
    assert [unit.args for unit in units] == [("kb1", "kb1-f")]
    assert run["document_ids"] == ["kb1/kb1-f"]
    assert run["unsafe_knowledge_ids"] == ["kb2", "kb3"]
    assert nxt.task == "app.tasks.finish_sync"


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    copied = {
        "groups": ["g1", "g-gone"],
        "synced-collections": ["kb1", "kb-gone"],
        "synced-documents": ["kb1/f1", "kb1/f-gone", "kb2/f-kept"],
    }
    fake.list_synced.side_effect = lambda kind, source: list(copied[kind])
    monkeypatch.setattr(tasks, "backend_client", fake)
    return fake


def _run(**overrides) -> dict:
    return {
        "id": "r",
        "group_ids": ["g1"],
        "knowledge_ids": ["kb1", "kb2"],
        "document_ids": ["kb1/f1"],
        "unsafe_knowledge_ids": ["kb2"],
        "group_errors": [],
        "knowledge_errors": [],
        "knowledge_inconsistent": [],
        **overrides,
    }


def test_what_is_gone_from_open_webui_is_dropped_files_first(backend):
    account = tasks.finish_sync.run([{"id": "x"}], _run())

    assert [call.args for call in backend.delete_synced.call_args_list] == [
        ("synced-documents", "owui", "kb1/f-gone"),
        ("synced-collections", "owui", "kb-gone"),
        ("groups", "owui", "g-gone"),
    ]
    assert account["files"]["dropped"] == 1 and account["knowledge_bases"]["dropped"] == 1


def test_the_files_of_a_knowledge_base_that_could_not_be_listed_are_kept(backend):
    tasks.finish_sync.run([], _run())

    dropped = [call.args[2] for call in backend.delete_synced.call_args_list]
    assert "kb2/f-kept" not in dropped


def test_nothing_is_dropped_when_open_webui_lists_none_while_muffin_has_some(backend):
    tasks.finish_sync.run([], _run(group_ids=[], knowledge_ids=[], document_ids=[], unsafe_knowledge_ids=[]))

    backend.delete_synced.assert_not_called()


def test_the_account_counts_the_errors_of_each_phase(backend):
    errors = [{"status": "error", "error": "x", "object": "f"}]

    account = tasks.finish_sync.run(errors, _run(group_errors=errors, knowledge_errors=errors + errors))

    assert (account["groups"]["errors"], account["knowledge_bases"]["errors"], account["files"]["errors"]) == (1, 2, 1)


def test_an_error_is_returned_not_raised_so_that_the_phase_goes_on(monkeypatch):
    monkeypatch.setattr(tasks, "_MAX_RETRIES", 0)
    owui = MagicMock()
    owui.group.side_effect = RuntimeError("Open WebUI is down")
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)

    result = tasks.sync_group.apply(args=("g1",)).get()

    assert result == {"status": "error", "error": "RuntimeError: Open WebUI is down", "object": "g1"}


def test_a_transient_error_is_tried_again(monkeypatch):
    owui = MagicMock()
    owui.group.side_effect = [RuntimeError("busy"), OwuiGroup(id="g1", name="A")]
    owui.group_members.return_value = iter([])
    backend = MagicMock()
    backend.sync_group.return_value = {"id": "x"}
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
    monkeypatch.setattr(tasks, "backend_client", backend)

    result = tasks.sync_group.apply(args=("g1",)).get()

    assert result["id"] == "x"
    assert owui.group.call_count == 2


def test_a_fact_about_the_object_is_not_tried_again(monkeypatch):
    owui = MagicMock()
    owui.file.return_value = OwuiFile(id="f1", filename="a.pdf", path="/local/a.pdf")
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)

    result = tasks.sync_knowledge_file.apply(args=("kb1", "f1")).get()

    assert result["status"] == "error" and "not in S3" in result["error"]
    assert owui.file.call_count == 1


def test_the_knowledge_bases_whose_vectors_do_not_match_are_counted_in_the_account(backend):
    inconsistent = [{"knowledge_id": "kb1", "problems": ["vectors of dimension 1024, while m gives 3"]}]

    account = tasks.finish_sync.run([], _run(knowledge_inconsistent=inconsistent))

    assert account["knowledge_bases"]["inconsistent"] == 1


def test_the_results_that_report_problems_are_kept_for_the_account(monkeypatch, fan_out):
    owui = MagicMock()
    owui.knowledge_files.return_value = []
    monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
    run = {"id": "r", "knowledge_ids": ["kb1", "kb2"]}

    tasks.sync_files.run(
        [
            {"id": "x", "knowledge_id": "kb1", "vector_problems": ["its collection is not in Qdrant"]},
            {"id": "y", "knowledge_id": "kb2", "vector_problems": []},
            {"status": "error", "error": "boom", "object": "kb3"},
        ],
        run,
    )

    assert run["knowledge_inconsistent"] == [{"knowledge_id": "kb1", "problems": ["its collection is not in Qdrant"]}]
