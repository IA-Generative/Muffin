"""Promptfoo provider: the evaluation judge, exposed as a custom provider so it can talk to
the backend's own /internal/llm/chat instead of an OpenAI-compatible proxy.

Like provider.py, this runs inside a promptfoo-spawned subprocess and must NOT import
anything from the worker's `app` package. Everything it needs arrives via
`options["config"]`, which the task writes into the generated YAML:

- backend_url:   the backend's base URL (e.g. http://backend:8000)
- api_key_envar: the environment variable holding the shared WORKER_API_KEY - the key
                 itself is deliberately NOT in this config: promptfoo replays the whole
                 config into results.json, which is uploaded as a stored artifact
- judge_model:   the collection's "evaluation" model, which scores every assertion
- collection_id: the collection under evaluation, so the judge's tokens are attributed
                 to its owner like every other worker call

promptfoo hands this provider the grading prompt it built for a model-graded assertion
(factuality, context-faithfulness) as `prompt`; the provider returns the judge's answer
as `{"output": ...}`, which promptfoo then parses for the score. temperature is pinned to
0 so the grading is as deterministic as the hub allows.
"""

import os

import httpx


def call_api(prompt: str, options: dict, context: dict) -> dict:  # noqa: ARG001
    config = options["config"]
    headers = {"X-API-Key": os.environ[config["api_key_envar"]]}
    base_url = config["backend_url"].rstrip("/")

    response = httpx.post(
        f"{base_url}/api/internal/llm/chat",
        json={
            "model": config["judge_model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "usage": {"step": "evaluation", "collection_id": config["collection_id"]},
        },
        headers=headers,
        timeout=120.0,
    )
    response.raise_for_status()
    return {"output": response.json()["content"]}
