"""Promptfoo test loader: turns the QA pairs of a collection into promptfoo tests.

Like provider.py, this runs inside a promptfoo-spawned subprocess and must not
import the worker's `app` package. It reads `pairs.json` - written by the task,
which has already filtered the pairs (evaluable, validated_only) - and maps each
one to a promptfoo test:

- the question becomes the prompt (the YAML's `{{query}}` template) and the `query`
  var - promptfoo's RAG assertions (context-faithfulness) require a var literally
  named `query` to hold the user's question,
- the pair's answer becomes the factuality ground truth,
- `validated`/`golden`/`qa_pair_id` ride along as vars so the backend can
  normalize the results without a second lookup.

Each test carries two model-graded assertions, both scored by the same judge:
- `factuality`: is the generated answer factually consistent with the expected
  answer (promptfoo's OpenAI-evals-style grader)?
- `context-faithfulness`: is the generated answer supported by the context the
  pipeline actually retrieved (RAGAS-style: the judge extracts the answer's
  claims, then checks each against the context)? The context comes from the
  provider's own output via `contextTransform: output.context` - the retrieved
  chunks, not a static fixture, so the score measures the real pipeline.

The filtering lives in the task, not here: the dedup hash and the tests must be
computed over exactly the same set of pairs.
"""

import json
from pathlib import Path

# Below these scores a test is colored as failed in the report - the scores
# themselves are still recorded either way (see the plan: the threshold colors,
# it never drops a result). Same threshold for both assertions: one coloring
# rule, simple to read in the report.
_FACTUALITY_THRESHOLD = 0.7
_CONTEXT_FAITHFULNESS_THRESHOLD = 0.7

# The namedScores keys the assertions write into results.json - the backend's
# artifact reader averages exactly these names (keep in sync with
# backend/app/services/evaluation_artifacts.py).
_FACTUALITY_METRIC = "factuality"
_CONTEXT_FAITHFULNESS_METRIC = "context_faithfulness"


def create_tests(config: dict | None = None) -> list[dict]:
    config = config or {}
    pairs = json.loads(Path(config["pairs_file"]).read_text())

    tests = []
    for pair in pairs:
        tests.append(
            {
                "vars": {
                    "query": pair["question"],
                    "reference": pair["answer"],
                    "validated": bool(pair["validated"]),
                    "golden": bool(pair.get("golden")),
                    "qa_pair_id": str(pair["id"]),
                },
                "assert": [
                    {
                        "type": "factuality",
                        "value": pair["answer"],
                        "threshold": _FACTUALITY_THRESHOLD,
                        "metric": _FACTUALITY_METRIC,
                    },
                    {
                        # The context the provider itself retrieved (its output.context -
                        # the k chunks), not a static reference: the score measures whether
                        # the generated answer stays grounded in what the pipeline found.
                        "type": "context-faithfulness",
                        "contextTransform": "output.context",
                        "threshold": _CONTEXT_FAITHFULNESS_THRESHOLD,
                        "metric": _CONTEXT_FAITHFULNESS_METRIC,
                    },
                ],
            }
        )
    return tests
