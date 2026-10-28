import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, TypedDict

import yaml
from loguru import logger
from pydantic import BaseModel, Field

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.config import settings
from app.promptfoo.create_tests import SCORED_METRICS

# At least 2 assistant turns are needed for "do these answers contradict each other" to mean
# anything - a single-turn conversation has nothing to compare across (see #31).
_MIN_ASSISTANT_TURNS_FOR_DISCUSSION_SCORE = 2

_DISCUSSION_SYSTEM_PROMPT = (
    "You are judging the quality of a multi-turn conversation between a user and an AI assistant "
    "that answers questions using a knowledge base. Judge two things, independently:\n"
    "1. Coherence: do the assistant's answers contradict each other across turns? List any "
    "specific contradictions found, quoting or paraphrasing the conflicting statements.\n"
    "2. Context usage: when a question depends on earlier conversation context (a pronoun, or an "
    "implicit reference to something discussed before), did the assistant correctly resolve and "
    "use that context rather than answering as if the question were asked in isolation? Score "
    "this from 0.0 (never handled correctly) to 1.0 (always handled correctly), and list any "
    "turns where context was mishandled.\n"
    'Respond only with JSON: {"coherent": bool, "coherence_issues": [array of short strings, '
    'empty if none], "context_usage_score": number between 0.0 and 1.0, "context_usage_issues": '
    '[array of short strings, empty if none], "reasoning": short string summarizing the verdict}.'
)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:] if lines else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_transcript(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"{message['role'].capitalize()}: {message['content']}" for message in messages)


def _transcript_hash(messages: list[dict[str, Any]]) -> str:
    """SHA-256 of the transcript - role + content of every message, in order. This is what
    DiscussionScore.content_hash stores: re-scoring the exact same conversation with the same
    model is a no-op (the worker skips it), but a conversation that grows gets re-scored.
    """
    payload = json.dumps(
        [{"role": m["role"], "content": m["content"]} for m in messages],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiscussionJudgment(BaseModel):
    """The judge's verdict on a conversation - the shape _DISCUSSION_SYSTEM_PROMPT asks the model
    to return. Validated on the way in: the response is untrusted, and a malformed one must fall
    back rather than crash the task."""

    coherent: bool
    coherence_issues: list[str] = Field(default_factory=list)
    context_usage_score: float
    context_usage_issues: list[str] = Field(default_factory=list)
    reasoning: str | None = None


_FALLBACK_JUDGMENT = DiscussionJudgment(
    coherent=True,
    context_usage_score=1.0,
    reasoning="The model's response could not be parsed as a judgment - defaulting to no "
    "issues found rather than reporting a fabricated problem.",
)


def _judge_discussion(model: str, transcript: str) -> DiscussionJudgment:
    """Never lets a malformed or refused LLM response take the task down - same reasoning as
    worker/agent_execution's json_chat: a conservative fallback (no issues found) beats crashing,
    and beats fabricating a specific problem the model never actually reported."""
    try:
        raw = backend_client.llm_chat(
            model,
            [
                {"role": "system", "content": _DISCUSSION_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
        )
        return DiscussionJudgment.model_validate_json(_strip_code_fence(raw))
    except Exception:
        logger.exception("Discussion judgment call failed, falling back to a conservative default")
        return _FALLBACK_JUDGMENT


# The metrics a run scores, straight from create_tests.py (its assertions, by their
# namedScores key) - part of the dedup hash: a run that also scores context faithfulness
# must not be deduped against an older one that scored factuality alone, its artifact
# would lack the new score. create_tests.py is the single source on the worker side;
# the backend keeps its own copy of the list (it cannot import worker code - see
# app/services/evaluation_service.py's _SCORED_METRICS).


class ConfigMuffin(TypedDict):
    """The run's configuration as replayed into results.json's metadata.config_muffin - the
    self-describing block that makes the stored artifact readable on its own."""

    collection_id: str
    k: int
    judge_model: str
    generator_model: str
    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    validated_only: bool
    content_hash: str
    provider_code_sha256: str


class RunCounts(TypedDict):
    """The counters read from the artifact, persisted on the EvaluationRun row."""

    pair_count: int
    golden_pair_count: int
    validated_pair_count: int
    unvalidated_pair_count: int


class RunPayload(RunCounts):
    """The payload the backend persists as the EvaluationRun row: the run's config under the
    backend's snapshot_* column names, the dedup hash, and the counters."""

    k: int
    llm_model: str
    snapshot_chunking_strategy: str
    snapshot_chunk_size: int
    snapshot_chunk_overlap: int
    snapshot_embedding_model: str
    content_hash: str


class EvaluationConfig(BaseModel):
    """Every parameter that shapes an evaluation run, in one place: the collection and its
    chunking/embedding snapshot, k, the judge and generator models, and the validated_only
    scope. It is the single source for both the dedup hash (content_hash) and the run's
    self-describing metadata.config_muffin block, so the two can never drift apart.

    MUST stay in sync with the backend's copy of the hash in
    app/services/evaluation_service.py - the trigger-time dedup check computes the same
    digest to answer "skipped" before dispatching. Both sides pin the same fixture digest
    in their tests (tests/test_tasks.py here, tests/services/test_evaluation_service.py
    there) so a drift breaks them.
    """

    collection_id: str
    # Display name only - it titles the promptfoo report, it never enters the hash.
    collection_name: str
    k: int
    judge_model: str
    generator_model: str
    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    validated_only: bool

    @classmethod
    def from_collection(
        cls,
        collection_id: str,
        collection_settings: dict[str, Any],
        k: int,
        judge_model: str,
        generator_model: str,
        validated_only: bool,
    ) -> "EvaluationConfig":
        """Builds the run's config from the collection's settings snapshot and the resolved
        models - the one place the internal settings payload is unpacked."""
        return cls(
            collection_id=collection_id,
            collection_name=collection_settings["name"],
            k=k,
            judge_model=judge_model,
            generator_model=generator_model,
            chunking_strategy=collection_settings["chunking_strategy"],
            chunk_size=collection_settings["chunk_size"],
            chunk_overlap=collection_settings["chunk_overlap"],
            embedding_model=collection_settings["embedding_model"],
            validated_only=validated_only,
        )

    def content_hash(self, qa_pairs: list[dict[str, Any]]) -> str:
        """SHA-256 of everything that affects the run's result: the QA pairs (id, question,
        answer, document_id, relevant documents, validated, golden), the chunking/embedding
        config, k, the judge model, the generator model (it writes the answers the judge
        scores), the scored metrics (the assertions the tests carry), and the validated_only
        scope. If none of these changed since the last run with the same models, the result
        would be identical and there's no reason to re-run (same dedup strategy as
        _transcript_hash for DiscussionScore).
        """
        payload = {
            "qa_pairs": _pairs_fingerprint(qa_pairs),
            "chunking_strategy": self.chunking_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "k": self.k,
            # The hash key is llm_model (the DB column); the domain term is judge_model.
            "llm_model": self.judge_model,
            "generator_model": self.generator_model,
            "scored_metrics": SCORED_METRICS,
            "validated_only": self.validated_only,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def config_muffin(self, content_hash: str, provider_code_sha256: str) -> ConfigMuffin:
        """The run's whole configuration, replayed into results.json so the stored artifact
        is self-describing: everything that made the results what they are is readable from
        results.json itself."""
        return {
            "collection_id": self.collection_id,
            "k": self.k,
            "judge_model": self.judge_model,
            "generator_model": self.generator_model,
            "chunking_strategy": self.chunking_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "validated_only": self.validated_only,
            "content_hash": content_hash,
            "provider_code_sha256": provider_code_sha256,
        }

    def run_payload(self, content_hash: str, counts: RunCounts) -> RunPayload:
        """The payload the backend persists as the EvaluationRun row: the run's config
        (snapshotted under the backend's snapshot_* column names) plus the dedup hash and the
        counters read from the artifact. The per-pair scores stay in results.json - this is
        only the slim, self-describing summary."""
        return {
            "k": self.k,
            "llm_model": self.judge_model,
            "snapshot_chunking_strategy": self.chunking_strategy,
            "snapshot_chunk_size": self.chunk_size,
            "snapshot_chunk_overlap": self.chunk_overlap,
            "snapshot_embedding_model": self.embedding_model,
            "content_hash": content_hash,
            **counts,
        }


def _pairs_fingerprint(qa_pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The QA pairs reduced to exactly what the dedup hash covers, sorted by id so the digest
    is order-independent."""
    return [
        {
            "id": p["id"],
            "question": p["question"],
            "answer": p["answer"],
            "document_id": str(p["document_id"]) if p.get("document_id") else None,
            "validated": p["validated"],
            "golden": bool(p.get("golden")),
            "relevant_document_ids": sorted(str(i) for i in (p.get("relevant_document_ids") or [])),
        }
        for p in sorted(qa_pairs, key=lambda p: p["id"])
    ]


def _relevant_documents(pair: dict[str, Any]) -> list[str]:
    """Every document that holds the pair's answer: a golden pair can name several, any other pair has
    its one source document. Empty when there is none, which means nothing to score against."""
    listed = [str(document_id) for document_id in (pair.get("relevant_document_ids") or [])]
    if listed:
        return list(dict.fromkeys(listed))
    return [str(pair["document_id"])] if pair.get("document_id") else []


def _write_promptfoo_dir(
    directory: Path,
    *,
    config: EvaluationConfig,
    pairs: list[dict[str, Any]],
    content_hash: str,
) -> None:
    """Lays out everything promptfoo needs in one throwaway directory: the generated YAML, the
    provider and test-loader modules copied next to it (promptfoo resolves file:// paths relative
    to the YAML), and the already-filtered QA pairs as pairs.json.

    The YAML is built as a dict then safe_dumped - never string-interpolated - so a question or
    a model name can never inject YAML structure. No secret is written into it: both the judge
    (apiKeyEnvar) and the provider (api_key_envar) read WORKER_API_KEY from the environment the
    subprocess inherits, because promptfoo replays the whole config into results.json - a stored
    artifact.

    metadata.config_muffin records the run's whole configuration (models, k, chunking/embedding
    snapshot, scope, dedup hash, provider code digest) so the stored artifact is self-describing:
    everything that made the results what they is readable from results.json itself.
    """
    for module in ("provider.py", "create_tests.py"):
        shutil.copy2(Path(__file__).parent / "promptfoo" / module, directory / module)
    (directory / "pairs.json").write_text(json.dumps(pairs, ensure_ascii=False))

    # The generation prompt and code live in provider.py, copied next to the YAML - their
    # digest is the only trace of the worker's own version in the artifact.
    provider_code_sha256 = hashlib.sha256(
        (Path(__file__).parent / "promptfoo" / "provider.py").read_bytes()
    ).hexdigest()

    promptfoo_config = {
        "description": f"Muffin evaluation - {config.collection_name}",
        # A first-class promptfoo tag (filterable, shown in the report) naming the
        # collection this run evaluated - the same id also rides in metadata.config_muffin,
        # but a tag is what promptfoo's own tooling reads.
        "tags": {"collection_id": config.collection_id},
        "metadata": {
            "config_muffin": config.config_muffin(content_hash, provider_code_sha256),
        },
        # Never send any result to promptfoo's servers.
        "sharing": False,
        # The question var is named `query` - promptfoo's RAG assertions (context-faithfulness)
        # require a var literally named `query`.
        "prompts": ["{{query}}"],
        "providers": [
            {
                "id": "file://provider.py",
                "label": "muffin-retrieval",
                "config": {
                    "backend_url": settings.BACKEND_API_URL,
                    "api_key_envar": "WORKER_API_KEY",
                    "collection_id": config.collection_id,
                    "k": config.k,
                    "generator_model": config.generator_model,
                },
            }
        ],
        "defaultTest": {
            "options": {
                # The judge: the collection's "evaluation" model, through the backend's
                # OpenAI-compatible proxy. X-Collection-Id makes the proxy attribute the
                # judge's tokens to the collection's owner.
                "provider": {
                    "id": f"openai:chat:{config.judge_model}",
                    "config": {
                        "apiBaseUrl": f"{settings.BACKEND_API_URL}/api/internal/v1",
                        "apiKeyEnvar": "WORKER_API_KEY",
                        "temperature": 0,
                        "headers": {"X-Collection-Id": config.collection_id},
                    },
                },
                # The provider returns {answer, context}: factuality scores the answer against
                # the expected one, context-faithfulness checks it against the retrieved
                # context (via the assertion's own contextTransform: output.context).
                "transform": "output.answer",
            }
        },
        "tests": [
            {
                "path": "file://create_tests.py:create_tests",
                "config": {"pairs_file": "pairs.json"},
            }
        ],
        "evaluateOptions": {"maxConcurrency": settings.EVAL_CONCURRENCY},
    }
    (directory / "promptfooconfig.yaml").write_text(yaml.safe_dump(promptfoo_config, sort_keys=False))


# promptfoo exits 100 when at least one test failed its threshold - that is a legitimate
# evaluation outcome (a low factuality score), not an execution error. Anything else (1,
# timeout, missing binary) means the run itself broke and the task must fail.
_PROMPTFOO_OK_EXIT_CODES = (0, 100)


def _run_promptfoo(directory: Path) -> tuple[bytes, bytes]:
    """Runs `promptfoo eval` in the directory and returns (results.json, report.html) - the
    subprocess inherits this process's environment, so WORKER_API_KEY is visible to both the
    judge and the provider without ever being written to disk."""
    binary = shutil.which("promptfoo")
    if binary is None:
        raise RuntimeError(
            "promptfoo is not installed - the evaluation worker image must bundle Node.js and "
            "a pinned promptfoo (see worker/evaluation/Dockerfile)"
        )
    completed = subprocess.run(  # noqa: S603
        [
            binary,
            "eval",
            "--config",
            "promptfooconfig.yaml",
            "--output",
            "results.json",
            "--output",
            "report.html",
            "--no-cache",
            "--no-progress-bar",
            "--no-table",
            # Keep promptfoo's own copy of the results out of the container: the task
            # uploads the artifacts it needs itself.
            "--no-write",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=settings.EVAL_TIMEOUT_SECONDS,
    )
    if completed.returncode not in _PROMPTFOO_OK_EXIT_CODES:
        logger.error(f"promptfoo exited with {completed.returncode}:\n{completed.stdout}\n{completed.stderr}")
        raise RuntimeError(f"promptfoo eval failed with exit code {completed.returncode}")

    results = (directory / "results.json").read_bytes()
    report = (directory / "report.html").read_bytes()
    # A results.json that does not parse means the run did not produce what we expect - fail
    # the task rather than persist a run built on a misread artifact.
    json.loads(results)
    return results, report


def _counts_from_results(results_json: bytes) -> RunCounts:
    """The run's counters, read from what actually ran (the artifact) rather than from what was
    intended (pairs.json) - the artifact is the truth. Golden pairs are counted apart, exactly
    like the old metric columns did: they are the human-written test set."""
    tests = json.loads(results_json)["results"]["results"]
    golden = [_coerce_bool(t.get("vars", {}).get("golden")) for t in tests]
    validated = [_coerce_bool(t.get("vars", {}).get("validated")) for t in tests]
    return {
        "pair_count": len(tests),
        "golden_pair_count": sum(golden),
        "validated_pair_count": sum(v and not g for v, g in zip(validated, golden, strict=False)),
        "unvalidated_pair_count": sum(not v and not g for v, g in zip(validated, golden, strict=False)),
    }


def _coerce_bool(value: Any) -> bool:
    """promptfoo's vars come back as strings when loaded from some paths - "false" must not
    read as true (same coercion as the backend's evaluation_artifacts)."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


@celery_app.task(name="app.tasks.run_evaluation", bind=True)
def run_evaluation(self, collection_id: str, k: int | None = None, validated_only: bool = False) -> None:
    """Replays every QA pair of a collection through the same search the research agent uses,
    generates an answer from what was retrieved, and has the collection's "evaluation" model
    judge each answer twice: factuality against the expected answer, and context faithfulness
    against the context the pipeline actually retrieved - all of it driven by promptfoo (see
    app/promptfoo/): the task lays out a throwaway config directory, runs `promptfoo eval`,
    then posts one EvaluationRun back to the backend with the two artifacts (results.json +
    report.html) as its whole persistence (see #11 - the model has no in-progress state, so
    nothing is created until the evaluation succeeded). The per-pair scores and every aggregate
    are computed from the stored artifact at read time, on the backend. A golden pair can name
    several relevant documents; any other pair has its one source document. When validated_only
    is True, only validated QA pairs are evaluated; when False (default), all QA pairs with a
    source document are evaluated regardless of validation status. No self.request.id Task
    registration here, unlike worker/document_process's spawned tasks: this is a single task
    with no children, and the backend already creates its Task row itself right after
    dispatching it (see EvaluationService.trigger - it already knows the user at that point,
    no round trip needed).
    """
    k = k or settings.DEFAULT_TOP_K
    collection_settings = backend_client.get_collection_settings(collection_id)
    judge_model = (collection_settings.get("generation_models") or {}).get(
        "evaluation"
    ) or backend_client.get_default_chat_model()
    generator_model = backend_client.get_default_chat_model()
    if judge_model is None or generator_model is None:
        logger.warning(f"No chat model available to run evaluation for collection {collection_id}, skipping")
        return

    qa_pairs = backend_client.list_qa_pairs(collection_id)
    # A pair with no source document has nothing to score against, regardless of whether
    # it's validated.
    evaluable_pairs = [pair for pair in qa_pairs if _relevant_documents(pair)]
    # When validated_only is True, restrict to validated pairs only; when False (default),
    # evaluate all pairs with a source document - the run's validated/unvalidated breakdown
    # still separates them in the results.
    if validated_only:
        evaluable_pairs = [pair for pair in evaluable_pairs if pair.get("validated")]
    skipped = len(qa_pairs) - len(evaluable_pairs)
    if skipped:
        logger.info(f"Skipping {skipped} QA pair(s) with no source document")
    if not evaluable_pairs:
        logger.warning(f"No evaluable QA pairs for collection {collection_id}, nothing to run")
        return

    # Dedup: if an identical run already exists (same QA pairs content, same chunking/embedding
    # settings, same k, same judge AND generator models, same validated_only scope), skip - the
    # result would be identical. Same strategy as score_discussion's content_hash skip (see #31).
    config = EvaluationConfig.from_collection(
        collection_id, collection_settings, k, judge_model, generator_model, validated_only
    )
    content_hash = config.content_hash(qa_pairs)
    existing_id = backend_client.find_evaluation_run(collection_id, content_hash, judge_model)
    if existing_id is not None:
        logger.info(
            f"Evaluation run {existing_id} already exists for collection {collection_id} "
            f"with the same content hash and model, skipping"
        )
        return

    logger.info(
        f"Evaluating {len(evaluable_pairs)} QA pair(s) for collection {collection_id} at k={k} "
        f"(judge: {judge_model}, generator: {generator_model})"
    )

    with tempfile.TemporaryDirectory(prefix="muffin-eval-") as temp_dir:
        directory = Path(temp_dir)
        _write_promptfoo_dir(directory, config=config, pairs=evaluable_pairs, content_hash=content_hash)
        results_json, report_html = _run_promptfoo(directory)

    payload = config.run_payload(content_hash, _counts_from_results(results_json))
    run_id = backend_client.create_evaluation_run(collection_id, payload)
    backend_client.upload_evaluation_artifacts(collection_id, run_id, results_json, report_html)
    logger.info(
        f"Evaluation run {run_id} created for collection {collection_id}: {payload['pair_count']} pair(s) evaluated"
    )


@celery_app.task(name="app.tasks.score_discussion", bind=True)
def score_discussion(self, conversation_id: str, model: str | None = None) -> None:
    """Judges a whole conversation - not any one answer - for cross-turn coherence and correct
    use of conversational context (see #31). A single LLM judgment call, not a search-heavy loop
    like run_evaluation, but shares its queue/service since neither needs its own. No
    self.request.id Task registration here either, same reasoning as run_evaluation: the backend
    already creates the Task row itself at dispatch time (see ConversationService.
    trigger_discussion_score).

    When `model` is None, the hub's default chat model is used. When set, that specific model is
    used - the (conversation, content_hash, model) unique index means re-scoring the same
    transcript with a different model creates a new score row instead of being a no-op.
    """
    messages = backend_client.list_conversation_messages(conversation_id)
    assistant_turns = sum(1 for message in messages if message["role"] == "assistant")
    if assistant_turns < _MIN_ASSISTANT_TURNS_FOR_DISCUSSION_SCORE:
        logger.warning(
            f"Conversation {conversation_id} has only {assistant_turns} assistant turn(s), "
            "nothing to compare across turns - skipping"
        )
        return

    if model is None:
        model = backend_client.get_default_chat_model()
    if model is None:
        logger.warning(f"No chat model available to score conversation {conversation_id}, skipping")
        return

    content_hash = _transcript_hash(messages)
    existing_id = backend_client.find_discussion_score(conversation_id, content_hash, model)
    if existing_id is not None:
        logger.info(
            f"Conversation {conversation_id} already scored with model {model} for this "
            f"transcript (score {existing_id}), skipping"
        )
        return

    logger.info(f"Scoring conversation {conversation_id}: {len(messages)} message(s), {assistant_turns} turn(s)")
    judgment = _judge_discussion(model, _build_transcript(messages))

    payload = {
        "message_count": len(messages),
        "llm_model": model,
        "content_hash": content_hash,
        "coherent": judgment.coherent,
        "coherence_issues": judgment.coherence_issues,
        "context_usage_score": judgment.context_usage_score,
        "context_usage_issues": judgment.context_usage_issues,
        "reasoning": judgment.reasoning,
    }
    score_id = backend_client.create_discussion_score(conversation_id, payload)
    logger.info(f"Discussion score {score_id} created for conversation {conversation_id}")
