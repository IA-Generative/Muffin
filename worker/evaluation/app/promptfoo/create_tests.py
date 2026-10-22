"""Promptfoo test loader: turns the QA pairs of a collection into promptfoo tests.

Like provider.py, this runs inside a promptfoo-spawned subprocess and must not
import the worker's `app` package. It reads `pairs.json` - written by the task,
which has already filtered the pairs (evaluable, validated_only) - and maps each
one to a promptfoo test:

- the question becomes the prompt (the YAML's `{{question}}` template),
- the pair's answer becomes the factuality ground truth,
- `validated`/`golden`/`qa_pair_id` ride along as vars so the backend can
  normalize the results without a second lookup.

The filtering lives in the task, not here: the dedup hash and the tests must be
computed over exactly the same set of pairs.
"""

import json
from pathlib import Path

# Below this factuality score a test is colored as failed in the report - the
# score itself is still recorded either way (see the plan: the threshold colors,
# it never drops a result).
_FACTUALITY_THRESHOLD = 0.7


def create_tests(config: dict | None = None) -> list[dict]:
    config = config or {}
    pairs = json.loads(Path(config["pairs_file"]).read_text())

    tests = []
    for pair in pairs:
        tests.append(
            {
                "vars": {
                    "question": pair["question"],
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
                        "metric": "factuality",
                    }
                ],
            }
        )
    return tests
