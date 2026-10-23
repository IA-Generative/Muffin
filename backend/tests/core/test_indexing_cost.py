import json
from pathlib import Path

import pytest

from app.core.indexing_cost import estimate_llm_calls
from app.schemas.collection import PipelineWindowsOut

CASES = json.loads((Path(__file__).parents[3] / "docs" / "indexing-llm-calls-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_estimate_matches_the_reference_cases(case):
    windows = PipelineWindowsOut(**case["windows"]).model_dump()

    estimate = estimate_llm_calls(case["pages"], windows, case["chunking_strategy"])

    assert estimate["chat"] == case["chat"]
    assert estimate["embeddings"]["qa_questions"] == case["embeddings"]["qa_questions"]


def test_the_reference_cases_hold_the_numbers_of_the_documentation():
    by_name = {case["name"]: case for case in CASES}

    assert by_name["900 pages, defaults"]["chat"]["total"] == 1978
    assert (
        by_name["900 pages, the example of the issue: summary 30 %, 100 questions, 20 % of the entities"]["chat"][
            "total"
        ]
        == 134
    )


def test_a_document_is_reported_sampled_only_above_the_minimum():
    windows = PipelineWindowsOut(summary_mode="percent", qa_max_questions=100).model_dump()

    assert not estimate_llm_calls(100, windows)["sampled"]
    assert estimate_llm_calls(101, windows)["sampled"]


def test_the_questions_never_go_over_the_cap():
    windows = PipelineWindowsOut(qa_max_questions=100).model_dump()

    for pages in (101, 250, 900, 5000):
        assert estimate_llm_calls(pages, windows)["embeddings"]["qa_questions"] <= 100


def test_a_short_document_costs_one_call_per_step():
    estimate = estimate_llm_calls(1, PipelineWindowsOut().model_dump())

    assert estimate["chat"] == {"chunking": 0, "summary": 1, "tagging": 1, "qa": 1, "entities": 1, "total": 4}
