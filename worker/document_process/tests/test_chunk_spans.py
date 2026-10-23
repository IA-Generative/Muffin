"""Where each chunk is in its pages, whatever the strategy cuts it with (#353)."""

import pytest

from app.chunking import PageText, chunk_pages

PAGES = [
    PageText(page_number=1, content="Alpha un.\n\nBeta deux."),
    PageText(page_number=2, content="  Gamma trois\n\nDelta quatre.  "),
    PageText(page_number=3, content="Epsilon cinq."),
]
BY_PAGE = {page.page_number: page.content for page in PAGES}


def _region(chunk) -> str:
    """The chunk as its spans read it in the pages themselves: the pieces of each page, joined as pages are."""
    return "\n\n".join(BY_PAGE[span["page"]][span["start"] : span["end"]] for span in chunk.spans)


def _cut(strategy: str, **options):
    settings = {"strategy": strategy, "chunk_size": 30, "chunk_overlap": 5, "window_pages": 2, "slide_pages": 1}
    return chunk_pages(PAGES, **{**settings, **options})


@pytest.mark.parametrize("strategy", ["fixed", "paragraphs", "semantic"])
def test_what_the_spans_say_is_the_chunk_s_text_in_its_pages(strategy):
    chunks = _cut(strategy)

    assert chunks
    for chunk in chunks:
        assert chunk.spans, chunk
        assert _region(chunk) == chunk.text


@pytest.mark.parametrize("strategy", ["fixed", "paragraphs", "semantic"])
def test_a_chunk_s_pages_are_the_first_and_last_of_its_spans(strategy):
    for chunk in _cut(strategy):
        assert (chunk.page_start, chunk.page_end) == (chunk.spans[0]["page"], chunk.spans[-1]["page"])


def test_a_paragraph_is_where_it_is_on_its_page():
    chunks = _cut("paragraphs")

    assert [(chunk.text, chunk.spans) for chunk in chunks][:2] == [
        ("Alpha un.", [{"page": 1, "start": 0, "end": 9}]),
        ("Beta deux.", [{"page": 1, "start": 11, "end": 21}]),
    ]


def test_the_blanks_the_text_is_stripped_of_are_not_in_its_interval():
    """Page 2 has spaces around its text: the chunk is "Gamma trois", its interval starts at the G."""
    chunk = next(chunk for chunk in _cut("paragraphs") if chunk.text == "Gamma trois")

    assert chunk.spans == [{"page": 2, "start": 2, "end": 13}]
    assert BY_PAGE[2][2:13] == "Gamma trois"


def test_a_fixed_chunk_cut_across_a_page_break_has_an_interval_on_each_page():
    chunks = _cut("fixed", chunk_size=40, chunk_overlap=0)

    across = [chunk for chunk in chunks if len(chunk.spans) > 1]
    assert across, "no chunk crosses a page"
    for chunk in across:
        assert chunk.page_start < chunk.page_end
        assert _region(chunk) == chunk.text


def test_a_fixed_chunk_that_overlaps_the_previous_one_is_still_at_its_own_place():
    chunks = _cut("fixed", chunk_size=20, chunk_overlap=10)

    for chunk in chunks:
        assert _region(chunk) == chunk.text


def test_a_semantic_chunk_has_its_own_page_and_not_the_pages_of_its_window():
    """Each chunk used to take the whole window's pages: the last paragraph of page 2 is cited on page 2."""
    chunks = _cut("semantic", window_pages=3)

    delta = next(chunk for chunk in chunks if chunk.text == "Delta quatre.")
    assert (delta.page_start, delta.page_end) == (2, 2)
    assert delta.spans == [{"page": 2, "start": 15, "end": 28}]


def test_paragraphs_the_model_groups_have_one_interval_per_page_from_the_first_to_the_last():
    chunks = chunk_pages(
        PAGES,
        "llm",
        500,
        50,
        window_pages=2,
        slide_pages=1,
        chunk_starts=lambda paragraphs: [0, 2] if len(paragraphs) > 2 else [0],
    )

    # Window pages 1-2: paragraphs Alpha, Beta | Gamma, Delta - grouped by the model as it begins them.
    first = chunks[0]
    assert first.text == "Alpha un.\n\nBeta deux."
    assert first.spans == [{"page": 1, "start": 0, "end": 21}]
    assert BY_PAGE[1][0:21] == first.text
    second = chunks[1]
    assert second.text == "Gamma trois\n\nDelta quatre."
    # From the G of Gamma to the final dot of Delta: the blank lines between the two are in the region.
    assert second.spans == [{"page": 2, "start": 2, "end": 28}]
    assert BY_PAGE[2][2:28] == second.text


def test_a_group_of_paragraphs_across_two_pages_has_an_interval_on_each():
    chunks = chunk_pages(
        PAGES,
        "llm",
        500,
        50,
        window_pages=2,
        slide_pages=1,
        chunk_starts=lambda paragraphs: [0],
    )

    (whole,) = chunks[:1]
    assert [span["page"] for span in whole.spans] == [1, 2]
    assert (whole.page_start, whole.page_end) == (1, 2)
    assert _region(whole) == whole.text


def test_a_page_with_nothing_but_blanks_makes_no_chunk_and_no_interval():
    pages = [PageText(page_number=1, content="  \n\n  "), PageText(page_number=2, content="Texte.")]

    chunks = chunk_pages(pages, "paragraphs", 100, 0, window_pages=2, slide_pages=1)

    assert [(chunk.text, chunk.page_start) for chunk in chunks] == [("Texte.", 2)]
