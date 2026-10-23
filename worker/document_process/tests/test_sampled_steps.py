from unittest.mock import MagicMock

from app import sampling
from app.config import settings as worker_settings
from app.tasks import _shared
from app.tasks import qa as qa_tasks
from app.windows import sliding_windows


def _windows(**changes):
    return {**_shared.PIPELINE_WINDOW_DEFAULTS, **changes}


def _text(count):
    return {page: "Some text on the page. " * 6 for page in range(1, count + 1)}


# -- the plans --------------------------------------------------------------------------------------------------


def test_a_document_that_is_not_long_gets_every_window_whatever_the_caps():
    windows = _windows(sampling_min_pages=100, qa_max_questions=3, extraction_percent=10)

    qa, per_window, drawn = sampling.plan_qa(50, windows, _text(50), seed=1)
    entities, entities_drawn = sampling.plan_entities(50, windows, _text(50), seed=1)

    assert qa == sliding_windows(50, windows["qa_window_pages"], windows["qa_slide_pages"])
    assert (per_window, drawn, entities_drawn) == (windows["qa_questions_per_window"], False, False)
    assert entities == sliding_windows(50, windows["extraction_window_pages"], windows["extraction_slide_pages"])


def test_the_questions_of_a_long_document_never_exceed_the_cap():
    windows = _windows(sampling_min_pages=100, qa_max_questions=25)

    selected, per_window, drawn = sampling.plan_qa(400, windows, _text(400), seed=3)

    assert drawn
    assert 0 < len(selected) * per_window <= 25
    assert len(set(selected)) == len(selected)
    assert selected == sorted(selected)


def test_the_windows_for_the_entities_follow_the_percent_then_the_cap():
    text = _text(400)
    pool = len(sampling.disjoint_windows(400, _shared.PIPELINE_WINDOW_DEFAULTS["extraction_window_pages"]))

    by_percent, drawn = sampling.plan_entities(400, _windows(extraction_percent=25), text, seed=3)
    capped, _ = sampling.plan_entities(400, _windows(extraction_percent=100, extraction_max_windows=5), text, seed=3)

    assert drawn and len(by_percent) == -(-pool * 25 // 100)
    assert len(capped) == 5


def test_the_plan_is_the_same_each_time_it_is_made():
    windows = _windows(sampling_min_pages=100, qa_max_questions=25, extraction_percent=30)
    seed = sampling.seed_for("doc-1", "hash", "qa")

    assert sampling.plan_qa(400, windows, _text(400), seed) == sampling.plan_qa(400, windows, _text(400), seed)
    assert sampling.plan_entities(400, windows, _text(400), seed) == sampling.plan_entities(
        400, windows, _text(400), seed
    )


# -- the lanes of drawn windows ---------------------------------------------------------------------------------


def test_a_lane_of_drawn_windows_carries_them_and_goes_on_through_them(monkeypatch):
    monkeypatch.setattr(worker_settings, "ENRICHMENT_WINDOW", 2)
    sent = []
    monkeypatch.setattr(_shared, "_spawn", lambda task, args, *rest, **kwargs: sent.append(args))
    monkeypatch.setattr(_shared, "raise_if_revoked", lambda: None)
    drawn = [(1, 2), (9, 10), (21, 22), (31, 32), (47, 48)]

    _shared.start_lanes(MagicMock(), "t", "doc", "col", drawn, (60, 2, 2), [3], "parent", drawn=True)

    assert [args[2:4] for args in sent] == [[1, 2], [9, 10]]
    lane = sent[0][-1]
    assert lane["windows"] == [list(window) for window in drawn] and "pages" not in lane

    # the window of a lane that ends sends the one 2 further in the list, windows that were not drawn skipped
    sent.clear()
    _shared.continue_lane(MagicMock(), "t", "doc", "col", lane, [3])
    assert sent[0][2:4] == [21, 22]
    _shared.continue_lane(MagicMock(), "t", "doc", "col", sent[0][-1], [3])
    assert sent[1][2:4] == [47, 48]


# -- the cap of the questions -----------------------------------------------------------------------------------


def test_a_model_that_gives_more_questions_than_asked_is_cut_to_what_was_asked(monkeypatch):
    backend = MagicMock()
    backend.get_collection_settings.return_value = {
        "instructions": {},
        "embedding_model": "embedder",
        "generation_models": {"qa": "model"},
    }
    backend.get_pages.return_value = [{"page_number": 1, "content": "Page one."}, {"page_number": 2, "content": "Two."}]
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(
        _shared,
        "_chat_json",
        lambda *args: [{"question": f"Q{n}?", "answer": f"A{n}", "evidence": ""} for n in range(5)],
    )

    qa_tasks._generate_qa_window("doc-1", "col-1", 1, 2, 2)

    stored = backend.replace_generated_qa.call_args.args[3]
    assert [pair["question"] for pair in stored] == ["Q0?", "Q1?"]
