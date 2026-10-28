import json
import os
import shutil
import stat
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml

from app import task_logging, tasks

# The real promptfoo binary, when the test runs somewhere it is installed (the worker image
# bundles it - see worker/evaluation/Dockerfile). Only the integration test below needs it.
_PROMPTFOO_BINARY = shutil.which("promptfoo")

# A minimal promptfoo results.json: the shape _counts_from_results and the backend's
# artifact reader both walk is results.results[*].vars + namedScores.
_RESULTS_JSON = {
    "results": {
        "results": [
            {
                "vars": {"query": "Validated?", "validated": True, "golden": False},
                "namedScores": {"factuality": 0.9, "context_faithfulness": 0.8},
            },
            {
                "vars": {"query": "Unvalidated?", "validated": False, "golden": False},
                "namedScores": {"factuality": 0.5, "context_faithfulness": 0.4},
            },
            {
                "vars": {"query": "Golden?", "validated": True, "golden": True},
                "namedScores": {"factuality": 1.0, "context_faithfulness": 1.0},
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
        "name": "Ma collection",
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
        "config": tasks.EvaluationConfig(
            collection_id="col-1",
            collection_name="Ma collection",
            k=5,
            judge_model="judge-model",
            generator_model="generator-model",
            chunking_strategy="paragraph",
            chunk_size=500,
            chunk_overlap=50,
            embedding_model="text-embedding-3-small",
            validated_only=False,
        ),
        "pairs": [_qa_pair("qa-1", "Question ?", "doc-1", validated=True)],
        "content_hash": "hash-1",
    }
    parameters.update(kwargs)
    tasks._write_promptfoo_dir(directory, **parameters)
    config = yaml.safe_load((directory / "promptfooconfig.yaml").read_text())
    return directory, config


def test_the_generated_yaml_wires_provider_judge_and_tests(tmp_path):
    directory, config = _written_config(tmp_path)

    # The evaluated collection is a first-class promptfoo tag (filterable, shown in the
    # report), not only a metadata entry.
    assert config["tags"] == {"collection_id": "col-1"}
    # The description names the collection by its title, not its opaque id.
    assert config["description"] == "Muffin evaluation - Ma collection"

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
    # The question var is named `query` - promptfoo's RAG assertions require it.
    assert config["prompts"] == ["{{query}}"]
    assert config["evaluateOptions"] == {"maxConcurrency": tasks.settings.EVAL_CONCURRENCY}

    # metadata.config_muffin: the run's whole configuration, replayed into results.json so
    # the stored artifact is self-describing.
    metadata = config["metadata"]["config_muffin"]
    assert metadata["collection_id"] == "col-1"
    assert metadata["k"] == 5
    assert metadata["judge_model"] == "judge-model"
    assert metadata["generator_model"] == "generator-model"
    assert metadata["chunking_strategy"] == "paragraph"
    assert metadata["chunk_size"] == 500
    assert metadata["chunk_overlap"] == 50
    assert metadata["embedding_model"] == "text-embedding-3-small"
    assert metadata["validated_only"] is False
    assert metadata["content_hash"] == "hash-1"
    assert len(metadata["provider_code_sha256"]) == 64

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


# A stand-in for the real provider.py: returns the shape promptfoo expects without hitting
# the network, so the eval below runs offline.
_MOCK_PROVIDER = (
    "def call_api(prompt, options, context):\n"
    '    return {"output": {"answer": "a", "context": ["c"]}, "context": ["c"], "metadata": {"sources": []}}\n'
)


@pytest.mark.integration
def test_the_promptfoo_results_never_contain_the_api_key(monkeypatch, tmp_path):
    # promptfoo replays the whole config into results.json - a stored artifact. The YAML
    # test above pins that the config only names the envar; this runs the real promptfoo
    # (the version the worker image pins) over that config with a sentinel key in the
    # environment, and asserts the key never lands in the artifact. Needs the real binary:
    # it runs in its own CI job (see .github/workflows/unit-tests.yml), never in the default
    # suite, so a missing binary fails loudly here instead of hiding as a silent skip.
    assert _PROMPTFOO_BINARY is not None, (
        "promptfoo is required for integration tests - see worker/evaluation/Dockerfile"
    )
    sentinel = "sentinel-worker-api-key-1234567890"
    monkeypatch.setenv("WORKER_API_KEY", sentinel)

    directory, config = _written_config(tmp_path)
    # The provider and the judge would both hit the network; swap them for a mock provider
    # and promptfoo's echo provider, and drop the judge-scored assertions. What is under
    # test is the config's api_key_envar/apiKeyEnvar placement, left exactly as generated.
    (directory / "provider.py").write_text(_MOCK_PROVIDER)
    config["defaultTest"]["options"]["provider"]["id"] = "echo"
    config["tests"] = [{"vars": {"query": "hello"}}]
    (directory / "promptfooconfig.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    completed = subprocess.run(  # noqa: S603
        [
            _PROMPTFOO_BINARY,
            "eval",
            "--config",
            "promptfooconfig.yaml",
            "--output",
            "results.json",
            "--no-cache",
            "--no-progress-bar",
            "--no-table",
            "--no-write",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode in (0, 100), completed.stderr

    results = (directory / "results.json").read_text()
    # The config really was replayed into the artifact (it is self-describing)...
    assert "config_muffin" in results
    # ...and the key is nowhere in it.
    assert sentinel not in results


def test_a_question_can_not_inject_yaml_structure(tmp_path):
    # The YAML is safe_dumped from a dict, never string-interpolated: a question holding
    # YAML or Jinja syntax stays a plain string var.
    malicious = "q: {{query}}\n  - injected: true"
    directory, config = _written_config(tmp_path, pairs=[_qa_pair("qa-1", malicious, "doc-1", validated=True)])

    assert config["prompts"] == ["{{query}}"]
    assert json.loads((directory / "pairs.json").read_text())[0]["question"] == malicious


# -- the dedup hash ------------------------------------------------------------------


def _config(**overrides):
    values = {
        "collection_id": "col-1",
        "collection_name": "Ma collection",
        "k": 5,
        "judge_model": "judge",
        "generator_model": "gen",
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "validated_only": False,
    }
    values.update(overrides)
    return tasks.EvaluationConfig(**values)


def test_the_evaluation_hash_covers_judge_generator_and_golden_pairs():
    generated = [_qa_pair("qa-1", "q", "doc-1", validated=True)]
    golden = {**_qa_pair("qa-2", "q2", "doc-1", validated=True), "golden": True, "relevant_document_ids": ["doc-1"]}

    base = _config().content_hash(generated)
    assert (
        len(
            {
                base,
                _config(judge_model="other-judge").content_hash(generated),
                _config(generator_model="other-gen").content_hash(generated),
                _config().content_hash([*generated, golden]),
                _config(k=8).content_hash(generated),
            }
        )
        == 5
    )


# The backend's trigger-time dedup (app/services/evaluation_service.py) computes the same
# digest over the same collection state to answer "skipped" before dispatching. Both sides
# pin this fixture's digest - if either hash drifts, these two tests disagree with it.
_VECTOR_PAIRS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "question": "Quelle est la réponse ?",
        "answer": "42",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "validated": True,
        "golden": False,
        "relevant_document_ids": [],
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "question": "Golden ?",
        "answer": "Oui.",
        "document_id": None,
        "validated": True,
        "golden": True,
        "relevant_document_ids": ["44444444-4444-4444-4444-444444444444", "22222222-2222-2222-2222-222222222222"],
    },
]
_VECTOR_SETTINGS = {
    "chunking_strategy": "paragraph",
    "chunk_size": 500,
    "chunk_overlap": 50,
    "embedding_model": "text-embedding-3-small",
}
_VECTOR_DIGEST = "d3e7f82d4a4799222175523743967e92b1d4dcddafec047443b3b2a4c32c28f0"


def test_the_evaluation_hash_matches_the_backend_vector():
    config = tasks.EvaluationConfig.from_collection(
        "col-1", {**_VECTOR_SETTINGS, "name": "Ma collection"}, 5, "judge-model", "gen-model", False
    )
    assert config.content_hash(_VECTOR_PAIRS) == _VECTOR_DIGEST


def test_run_payload_snapshots_the_config_and_folds_in_the_counts():
    # The backend persists this as the EvaluationRun row: the config under its snapshot_*
    # column names, the dedup hash, and the counters read from the artifact.
    config = _config(k=7, judge_model="judge-model", chunking_strategy="fixed", chunk_size=800, chunk_overlap=80)
    counts = {"pair_count": 3, "golden_pair_count": 1, "validated_pair_count": 1, "unvalidated_pair_count": 1}

    assert config.run_payload("hash-1", counts) == {
        "k": 7,
        "llm_model": "judge-model",
        "snapshot_chunking_strategy": "fixed",
        "snapshot_chunk_size": 800,
        "snapshot_chunk_overlap": 80,
        "snapshot_embedding_model": "text-embedding-3-small",
        "content_hash": "hash-1",
        **counts,
    }


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
