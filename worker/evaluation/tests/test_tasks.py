import json
import os
import stat
from unittest.mock import MagicMock

import pytest
import yaml

from app import task_logging, tasks

# A minimal promptfoo results.json: the shape _counts_from_results and the backend's
# artifact reader both walk is results.results[*].vars + namedScores.
_RESULTS_JSON = {
    "results": {
        "results": [
            {
                "vars": {"question": "Validated?", "validated": True, "golden": False},
                "namedScores": {"factuality": 0.9},
            },
            {
                "vars": {"question": "Unvalidated?", "validated": False, "golden": False},
                "namedScores": {"factuality": 0.5},
            },
            {
                "vars": {"question": "Golden?", "validated": True, "golden": True},
                "namedScores": {"factuality": 1.0},
            },
        ]
    }
}


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


def _qa_pair(id_: str, question: str, document_id: str | None, validated: bool, golden: bool = False):
    return {
        "id": id_,
        "question": question,
        "answer": "answer",
        "document_id": document_id,
        "validated": validated,
        "golden": golden,
    }


def _fake_promptfoo_on_path(monkeypatch, tmp_path, *, exit_code=0, results=_RESULTS_JSON, raw_results=None):
    """A promptfoo stand-in on PATH: writes both artifacts in its cwd, exits as told.
    raw_results, when given, is written verbatim - to simulate a broken artifact."""
    binary = tmp_path / "bin" / "promptfoo"
    binary.parent.mkdir(parents=True, exist_ok=True)
    payload = raw_results if raw_results is not None else json.dumps(results)
    script = (
        "#!/bin/sh\n"
        "cat > results.json <<'EOF'\n"
        f"{payload}\n"
        "EOF\n"
        "printf '%s' '<html>report</html>' > report.html\n"
        f"exit {exit_code}\n"
    )
    binary.write_text(script)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ.get('PATH', '')}")


def _run(monkeypatch, pairs, *, results=_RESULTS_JSON, exit_code=0, tmp_path=None, validated_only=False):
    """Wires a fake backend and (unless the caller wants the subprocess to fail) a fake
    promptfoo, runs the task, and returns the fake backend."""
    if tmp_path is not None:
        _fake_promptfoo_on_path(monkeypatch, tmp_path, exit_code=exit_code, results=results)

    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "generator-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = pairs
    fake.create_evaluation_run.return_value = "run-1"
    tasks.run_evaluation("col-1", 5, validated_only)
    return fake


def test_run_evaluation_posts_one_run_with_both_artifacts(monkeypatch, tmp_path):
    fake = _run(monkeypatch, [_qa_pair("qa-1", "q", "doc-1", validated=True)], tmp_path=tmp_path)

    fake.create_evaluation_run.assert_called_once()
    collection_id, payload = fake.create_evaluation_run.call_args.args
    assert collection_id == "col-1"
    # The slim metadata payload: no scores, no per-pair results - those live in the artifact.
    assert payload["k"] == 5
    assert payload["llm_model"] == "generator-model"  # no "evaluation" model configured: default
    assert payload["snapshot_chunking_strategy"] == "paragraph"
    assert payload["content_hash"]
    # Counters read from what actually ran, golden apart (same semantics as before).
    assert payload["pair_count"] == 3
    assert payload["golden_pair_count"] == 1
    assert payload["validated_pair_count"] == 1
    assert payload["unvalidated_pair_count"] == 1

    fake.upload_evaluation_artifacts.assert_called_once()
    _, run_id, results_json, report_html = fake.upload_evaluation_artifacts.call_args.args
    assert run_id == "run-1"
    assert json.loads(results_json) == _RESULTS_JSON
    assert report_html == b"<html>report</html>"


def test_run_evaluation_accepts_failed_tests_as_results(monkeypatch, tmp_path):
    # promptfoo exits 100 when a test scores below its threshold - a low factuality
    # score is an evaluation outcome, not an execution error.
    fake = _run(
        monkeypatch,
        [_qa_pair("qa-1", "q", "doc-1", validated=True)],
        exit_code=100,
        tmp_path=tmp_path,
    )

    fake.create_evaluation_run.assert_called_once()
    fake.upload_evaluation_artifacts.assert_called_once()


def test_run_evaluation_fails_without_artifacts_when_promptfoo_breaks(monkeypatch, tmp_path):
    # Exit 1 means the run itself broke: the task fails and nothing is persisted -
    # the model has no in-progress state (see #11).
    with pytest.raises(RuntimeError, match="exit code 1"):
        _run(monkeypatch, [_qa_pair("qa-1", "q", "doc-1", validated=True)], exit_code=1, tmp_path=tmp_path)


def test_run_evaluation_fails_on_an_unparseable_results_json(monkeypatch, tmp_path):
    # A results.json that does not parse means the run did not produce what we expect:
    # fail the task rather than persist a run built on a misread artifact.
    _fake_promptfoo_on_path(monkeypatch, tmp_path, raw_results="not json at all")

    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "m"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]

    with pytest.raises(json.JSONDecodeError):
        tasks.run_evaluation("col-1", 5)

    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_skips_qa_pairs_with_no_source_document(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "Manual pair?", None, validated=True)]

    tasks.run_evaluation("col-1", 5)

    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_restricts_to_validated_pairs_when_asked(monkeypatch, tmp_path):
    _fake_promptfoo_on_path(monkeypatch, tmp_path, results={"results": {"results": []}})

    # The filtering happens in the task, before pairs.json is written - the YAML's test
    # loader must receive only the pairs that will run.
    captured = {}
    original = tasks._write_promptfoo_dir

    def spy(directory, **kwargs):
        captured["pairs"] = kwargs["pairs"]
        original(directory, **kwargs)

    monkeypatch.setattr(tasks, "_write_promptfoo_dir", spy)

    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "m"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [
        _qa_pair("qa-1", "Validated", "doc-1", validated=True),
        _qa_pair("qa-2", "Not yet", "doc-1", validated=False),
    ]

    tasks.run_evaluation("col-1", 5, validated_only=True)

    assert [p["id"] for p in captured["pairs"]] == ["qa-1"]


def test_run_evaluation_skips_entirely_without_a_chat_model(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = None

    tasks.run_evaluation("col-1", 5)

    fake.list_qa_pairs.assert_not_called()
    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_prefers_a_configured_evaluation_model(monkeypatch, tmp_path):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    _fake_promptfoo_on_path(monkeypatch, tmp_path)

    fake.get_collection_settings.return_value = _fake_settings(generation_models={"evaluation": "judge-model"})
    fake.get_default_chat_model.return_value = "generator-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", 5)

    # The judge is the configured model; the generator stays the default one.
    _, payload = fake.create_evaluation_run.call_args.args
    assert payload["llm_model"] == "judge-model"


def test_run_evaluation_skips_when_an_identical_run_exists(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = "existing-run"
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]

    tasks.run_evaluation("col-1", 5)

    fake.create_evaluation_run.assert_not_called()


def test_run_evaluation_defaults_k_from_settings(monkeypatch, tmp_path):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)
    monkeypatch.setattr(tasks.settings, "DEFAULT_TOP_K", 7)
    _fake_promptfoo_on_path(monkeypatch, tmp_path)

    fake.get_collection_settings.return_value = _fake_settings()
    fake.get_default_chat_model.return_value = "test-model"
    fake.find_evaluation_run.return_value = None
    fake.list_qa_pairs.return_value = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    fake.create_evaluation_run.return_value = "run-1"

    tasks.run_evaluation("col-1", None)

    _, payload = fake.create_evaluation_run.call_args.args
    assert payload["k"] == 7


# -- the generated promptfoo directory -----------------------------------------------


def _written_config(tmp_path, **kwargs):
    """Runs _write_promptfoo_dir into a directory and returns (directory, parsed YAML)."""
    directory = tmp_path / "eval"
    directory.mkdir()
    parameters = {
        "collection_id": "col-1",
        "k": 5,
        "judge_model": "judge-model",
        "generator_model": "generator-model",
        "pairs": [_qa_pair("qa-1", "Question ?", "doc-1", validated=True)],
    }
    parameters.update(kwargs)
    tasks._write_promptfoo_dir(directory, **parameters)
    config = yaml.safe_load((directory / "promptfooconfig.yaml").read_text())
    return directory, config


def test_the_generated_yaml_wires_provider_judge_and_tests(tmp_path):
    directory, config = _written_config(tmp_path)

    provider = config["providers"][0]
    assert provider["id"] == "file://provider.py"
    assert provider["config"]["collection_id"] == "col-1"
    assert provider["config"]["k"] == 5
    assert provider["config"]["generator_model"] == "generator-model"
    assert provider["config"]["backend_url"] == tasks.settings.BACKEND_API_URL

    judge = config["defaultTest"]["options"]["provider"]
    assert judge["id"] == "openai:chat:judge-model"
    assert judge["config"]["apiBaseUrl"].endswith("/api/internal/v1")
    assert judge["config"]["headers"] == {"X-Collection-Id": "col-1"}
    assert config["defaultTest"]["options"]["transform"] == "output.answer"

    assert config["tests"][0]["path"] == "file://create_tests.py:create_tests"
    assert config["sharing"] is False
    assert config["evaluateOptions"] == {"maxConcurrency": tasks.settings.EVAL_CONCURRENCY}

    # The modules are copied next to the YAML (promptfoo resolves file:// relative to it)
    # and the pairs ride along as JSON.
    assert (directory / "provider.py").exists()
    assert (directory / "create_tests.py").exists()
    assert json.loads((directory / "pairs.json").read_text())[0]["question"] == "Question ?"


def test_the_generated_yaml_never_contains_the_api_key(tmp_path):
    # promptfoo replays the whole config into results.json - a stored artifact. The key
    # must only ever be read from the subprocess's inherited environment.
    _, config = _written_config(tmp_path)

    assert config["providers"][0]["config"]["api_key_envar"] == "WORKER_API_KEY"
    assert config["defaultTest"]["options"]["provider"]["config"]["apiKeyEnvar"] == "WORKER_API_KEY"
    if tasks.settings.WORKER_API_KEY:  # empty in tests, set in production - both must hold
        assert tasks.settings.WORKER_API_KEY not in yaml.safe_dump(config)


def test_a_question_can_not_inject_yaml_structure(tmp_path):
    # The YAML is safe_dumped from a dict, never string-interpolated: a question holding
    # YAML or Jinja syntax stays a plain string var.
    malicious = "q: {{question}}\n  - injected: true"
    directory, config = _written_config(tmp_path, pairs=[_qa_pair("qa-1", malicious, "doc-1", validated=True)])

    assert config["prompts"] == ["{{question}}"]
    assert json.loads((directory / "pairs.json").read_text())[0]["question"] == malicious


# -- the dedup hash ------------------------------------------------------------------


def test_the_evaluation_hash_covers_judge_generator_and_golden_pairs():
    settings = _fake_settings()
    generated = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    golden = {**_qa_pair("qa-2", "q2", "doc-1", validated=True), "golden": True, "relevant_document_ids": ["doc-1"]}

    base = tasks._evaluation_hash(generated, settings, 5, "judge", "gen")
    assert (
        len(
            {
                base,
                tasks._evaluation_hash(generated, settings, 5, "other-judge", "gen"),
                tasks._evaluation_hash(generated, settings, 5, "judge", "other-gen"),
                tasks._evaluation_hash([*generated, golden], settings, 5, "judge", "gen"),
                tasks._evaluation_hash(generated, settings, 8, "judge", "gen"),
            }
        )
        == 5
    )


def test_counts_from_results_coerce_string_vars():
    # promptfoo hands vars back as strings on some paths: "false" must not read as true.
    results = json.dumps(
        {
            "results": {
                "results": [
                    {"vars": {"validated": "true", "golden": "false"}},
                    {"vars": {"validated": "false", "golden": "false"}},
                    {"vars": {"validated": "true", "golden": "true"}},
                ]
            }
        }
    ).encode()

    assert tasks._counts_from_results(results) == {
        "pair_count": 3,
        "golden_pair_count": 1,
        "validated_pair_count": 1,
        "unvalidated_pair_count": 1,
    }
