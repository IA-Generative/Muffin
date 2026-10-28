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

A third assertion counts the retrieved chunks - a diagnostic, not a quality score:
it is scored under its own `context_chunk_count` metric (so it shows in the promptfoo
report) but the Muffin UI hides it (see frontend/src/utils/evaluationMetrics.ts). It
always passes: a test's success (and the pass rates the UI shows) must not depend on
how many chunks retrieval happened to return.

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

# The namedScores keys the assertions write into results.json. The backend serves
# these scores generically (whatever keys the artifact holds), so a new assertion
# here is all a new metric needs on the worker side - except the dedup hash: the
# backend's trigger-time copy (backend/app/services/evaluation_service.py's
# _SCORED_METRICS) must list it too, or a new-metric run would be deduped against
# an old artifact that lacks the new score.
_FACTUALITY_METRIC = "factuality"
_CONTEXT_FAITHFULNESS_METRIC = "context_faithfulness"
_CONTEXT_CHUNK_COUNT_METRIC = "context_chunk_count"

# Every metric the tests score, by namedScores key - the task folds this list into
# its dedup hash (see tasks.py's EvaluationConfig.content_hash). Keep sorted: the hash digest is
# order-sensitive, and the backend's copy lists the same order.
SCORED_METRICS = sorted([_FACTUALITY_METRIC, _CONTEXT_FAITHFULNESS_METRIC, _CONTEXT_CHUNK_COUNT_METRIC])

# The chunk count is a diagnostic, not a quality score: it is scored under its own
# `context_chunk_count` metric so it shows in the promptfoo report, but the Muffin UI
# hides it (frontend/src/utils/evaluationMetrics.ts) - the backend serves namedScores
# generically (see backend/app/services/evaluation_artifacts.py), so a metric here would
# otherwise surface there too. It always passes: a test's success (and the pass rates the
# UI shows) must not depend on how many chunks retrieval happened to return. The
# placeholder string must stay in sync with provider.py's "no context retrieved".
_COUNT_CONTEXT_CHUNKS_JS = """
const chunks = context.providerResponse?.context;
const count =
  Array.isArray(chunks) && !(chunks.length === 1 && chunks[0] === 'no context retrieved')
    ? chunks.length
    : 0;
return { pass: true, score: count, reason: `Retrieved ${count} context chunk(s)` };
"""


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
                    {
                        # A diagnostic, not a quality score: scored under its own metric
                        # (so it shows in the promptfoo report) but hidden by the Muffin UI.
                        "type": "javascript",
                        "value": _COUNT_CONTEXT_CHUNKS_JS,
                        "metric": _CONTEXT_CHUNK_COUNT_METRIC,
                    },
                ],
            }
        )
    return tests
