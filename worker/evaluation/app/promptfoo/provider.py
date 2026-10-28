"""Promptfoo provider: the Muffin RAG pipeline (search + answer generation) exposed as
one callable unit, so promptfoo can replay every QA pair through it.

This module runs inside a Python subprocess spawned by promptfoo (Node) - it must
NOT import anything from the worker's `app` package. Everything it needs arrives
via `options["config"]`, which the task writes into the generated YAML:

- backend_url:    the backend's base URL (e.g. http://backend:8000)
- api_key_envar:  the environment variable holding the shared WORKER_API_KEY - the key
                  itself is deliberately NOT in this config: promptfoo replays the whole
                  config into results.json, which is uploaded as a stored artifact
- collection_id:  the collection under evaluation
- k:              how many chunks to retrieve per question
- generator_model: the model that writes the answer from the retrieved excerpts

The judge (factuality scoring) is configured separately in the YAML's
defaultTest.options.provider - it is its own custom provider (judge_provider.py),
not this module.
"""

import os

import httpx

_ANSWER_SYSTEM_PROMPT = (
    "Answer the question using only the excerpts given below. If the excerpts don't contain "
    "enough information to answer, say so plainly rather than guessing."
)


def _search(base_url: str, headers: dict, config: dict, query: str) -> list[dict]:
    """The same search the research agent uses: /internal/search, k chunks."""
    response = httpx.post(
        f"{base_url}/api/internal/search",
        json={
            "collection_ids": [config["collection_id"]],
            "query": query,
            "limit": config["k"],
        },
        headers=headers,
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def _generate(base_url: str, headers: dict, config: dict, question: str, excerpts: str) -> str:
    """The answer, written from the retrieved excerpts by the collection's default chat model."""
    response = httpx.post(
        f"{base_url}/api/internal/llm/chat",
        json={
            "model": config["generator_model"],
            "messages": [
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nExcerpts:\n{excerpts}"},
            ],
            "usage": {"step": "run_evaluation", "collection_id": config["collection_id"]},
        },
        headers=headers,
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["content"]


def call_api(prompt: str, options: dict, context: dict) -> dict:  # noqa: ARG001
    """Runs the same search the research agent uses, then generates an answer from what
    was retrieved - one promptfoo test = one search + one generation.

    Returns the shape promptfoo expects: `output.answer` is what the factuality
    assertion scores (via defaultTest.options.transform), `context` feeds the
    grader's prompt, and `metadata.sources` is what the evaluations UI shows as
    the retrieved chunks (document_name#chunk_id, same format as before).
    """
    config = options["config"]
    headers = {"X-API-Key": os.environ[config["api_key_envar"]]}
    base_url = config["backend_url"].rstrip("/")

    results = _search(base_url, headers, config, prompt)
    if results:
        excerpts = "\n\n".join(f"[{i + 1}] {r['text']}" for i, r in enumerate(results))
        answer = _generate(base_url, headers, config, prompt, excerpts)
    else:
        answer = "No relevant excerpts were retrieved for this question."

    contexts = [r["text"] for r in results]
    if not contexts:
        # An empty context would leave the factuality grader with nothing to compare
        # against - a placeholder keeps the test well-formed instead.
        contexts = ["no context retrieved"]
    return {
        "output": {"answer": answer, "context": contexts},
        "context": contexts,
        "metadata": {"sources": [f"{r['document_name']}#{r['chunk_id']}" for r in results]},
    }
