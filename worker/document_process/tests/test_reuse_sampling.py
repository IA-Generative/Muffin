"""Reading only a part of a long document (#372) in the fingerprints of the stages (#300): a result made from a part
is not the result of the whole, so the settings that choose the part are part of it - and only when they do, so that
what was computed before stays reusable."""

from app import reuse
from app.tasks import _shared

FILE = "a" * 64


def _settings(**windows):
    return {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "embedder",
        "instructions": {"summary": "", "qa": "", "extraction": "", "tagging": ""},
        "generation_models": {"summary": "chat", "qa": "chat", "extraction": "chat", "tagging": "chat"},
        "pipeline_windows": windows,
    }


def test_the_fingerprints_of_what_was_computed_before_are_unchanged():
    """The payloads as they were before #372, rebuilt by hand: nothing may be added to them by default."""
    settings, windows = _settings(), _shared._windows(_settings())

    assert reuse.summary(FILE, settings, "chat") == reuse._digest(
        {
            **reuse._base(reuse.SUMMARY, FILE),
            "extraction": reuse._extraction_of(FILE),
            "model": "chat",
            "instructions": "",
            "pages_per_map": windows["summary_pages_per_map"],
        }
    )
    assert reuse.qa(FILE, settings, "chat") == reuse._digest(
        {
            **reuse._base(reuse.QA, FILE),
            "extraction": reuse._extraction_of(FILE),
            "model": "chat",
            "instructions": "",
            "window": windows["qa_window_pages"],
            "slide": windows["qa_slide_pages"],
            "questions": windows["qa_questions_per_window"],
        }
    )
    assert reuse.entities(FILE, settings, "chat") == reuse._digest(
        {
            **reuse._base(reuse.ENTITIES, FILE),
            "extraction": reuse._extraction_of(FILE),
            "positions": 1,
            "model": "chat",
            "instructions": "",
            "window": windows["extraction_window_pages"],
            "slide": windows["extraction_slide_pages"],
        }
    )


def test_settings_that_read_everything_do_not_change_a_fingerprint_whatever_they_say():
    base = _settings()
    inactive = _settings(summary_percent=10, summary_head_percent=5, sampling_min_pages=500, extraction_percent=100)

    assert reuse.summary(FILE, base, "chat") == reuse.summary(FILE, inactive, "chat")
    assert reuse.qa(FILE, base, "chat") == reuse.qa(FILE, inactive, "chat")
    assert reuse.entities(FILE, base, "chat") == reuse.entities(FILE, inactive, "chat")


def test_the_summary_depends_on_what_it_reads():
    whole = reuse.summary(FILE, _settings(), "chat")
    share = reuse.summary(FILE, _settings(summary_mode="percent", summary_percent=30), "chat")

    assert share != whole
    assert share != reuse.summary(FILE, _settings(summary_mode="percent", summary_percent=40), "chat")
    assert share != reuse.summary(
        FILE, _settings(summary_mode="percent", summary_head_percent=20, summary_tail_percent=10), "chat"
    )
    assert share != reuse.summary(
        FILE, _settings(summary_mode="percent", summary_percent=30, sampling_min_pages=50), "chat"
    )
    given = reuse.summary(FILE, _settings(summary_mode="pages", summary_page_ranges="1-5"), "chat")
    assert given not in (whole, share)
    assert given != reuse.summary(FILE, _settings(summary_mode="pages", summary_page_ranges="1-6"), "chat")


def test_the_qa_pairs_depend_on_the_cap():
    uncapped = reuse.qa(FILE, _settings(), "chat")

    assert reuse.qa(FILE, _settings(qa_max_questions=100), "chat") != uncapped
    assert reuse.qa(FILE, _settings(qa_max_questions=100), "chat") != reuse.qa(
        FILE, _settings(qa_max_questions=50), "chat"
    )


def test_the_entities_depend_on_the_share_and_the_cap_of_windows():
    all_of_them = reuse.entities(FILE, _settings(), "chat")
    share = reuse.entities(FILE, _settings(extraction_percent=20), "chat")

    assert share != all_of_them
    assert share != reuse.entities(FILE, _settings(extraction_percent=30), "chat")
    assert reuse.entities(FILE, _settings(extraction_max_windows=30), "chat") not in (all_of_them, share)


def test_the_tags_follow_the_summary_they_are_read_from():
    whole = reuse.tags(FILE, _settings(), "chat", "chat")

    assert reuse.tags(FILE, _settings(summary_mode="percent"), "chat", "chat") != whole
