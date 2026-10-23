"""Where a passage is on a page, and the rectangles to frame for it (#350)."""

from types import SimpleNamespace

from app.services.page_highlights import chunk_pages_of, chunk_spans_on, find_spans, locate_passage, rects_for_span

PAGE = "Article 1\nLe locataire paie son loyer\nchaque mois.\n\nArticle 2\nLe bail dure trois ans."


def _text(spans, content=PAGE):
    return [content[start:end] for start, end in spans]


class TestLocatePassage:
    def test_a_passage_is_found_where_it_is(self):
        assert _text(locate_passage(PAGE, "Le bail dure trois ans.")) == ["Le bail dure trois ans."]

    def test_line_breaks_spaces_and_case_do_not_matter(self):
        assert _text(locate_passage(PAGE, "le  LOCATAIRE paie son loyer chaque mois.")) == [
            "Le locataire paie son loyer\nchaque mois."
        ]

    def test_an_excerpt_truncated_with_ellipses_is_found_by_its_fragments(self):
        assert _text(locate_passage(PAGE, "... Le locataire paie son loyer ... Le bail dure trois ans ...")) == [
            "Le locataire paie son loyer",
            "Le bail dure trois ans",
        ]

    def test_the_paragraphs_of_a_chunk_are_each_found(self):
        passage = "Article 1\nLe locataire paie son loyer\nchaque mois.\n\nArticle 2"

        assert _text(locate_passage(PAGE, passage)) == [
            "Article 1\nLe locataire paie son loyer\nchaque mois.",
            "Article 2",
        ]

    def test_a_summary_of_the_zone_is_found_by_its_first_words(self):
        page = "Le bail dure trois ans à compter de la signature du contrat et se renouvelle."

        assert locate_passage(
            page, "Le bail dure trois ans à compter de la signature, puis renouvellement tacite."
        ) == [(0, len("Le bail dure trois ans à compter de"))]

    def test_nothing_is_returned_when_the_passage_is_not_there(self):
        assert locate_passage(PAGE, "Le propriétaire entretient l'immeuble") == []
        assert locate_passage(PAGE, "") == [] and locate_passage(PAGE, None) == [] and locate_passage("", "texte") == []

    def test_a_fragment_is_looked_for_after_the_previous_one(self):
        page = "Total 10\nAutre ligne\nTotal 20"

        assert _text(locate_passage(page, "Autre ligne\n\nTotal 20"), page) == ["Autre ligne", "Total 20"]
        assert locate_passage(page, "Autre ligne\n\nTotal 20")[1][0] > page.index("Autre")

    def test_regular_expression_characters_are_taken_literally(self):
        page = "Prix (HT) : 5,00 € [net]"

        assert _text(locate_passage(page, page), page) == [page]

    def test_a_short_text_asked_for_several_occurrences_gives_them_up_to_the_limit(self):
        page = "Paris est grande. Paris est belle. Paris est vieille."

        assert len(locate_passage(page, "Paris", max_occurrences=10)) == 3
        assert len(locate_passage(page, "Paris", max_occurrences=2)) == 2
        # By default one place: the passage's own.
        assert len(locate_passage(page, "Paris")) == 1

    def test_a_very_common_value_never_gives_more_than_ten_places(self):
        assert len(find_spans("Paris " * 50, "Paris", limit=10_000)) == 10


def _box(text, x_min, y_min, x_max, y_max, start, end, words=()):
    return SimpleNamespace(
        text=text,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        char_start=start,
        char_end=end,
        words=list(words),
    )


def _word(text, x_min, x_max, start, end):
    return {
        "text": text,
        "x_min": x_min,
        "y_min": 0.1,
        "x_max": x_max,
        "y_max": 0.2,
        "char_start": start,
        "char_end": end,
    }


class TestRectsForSpan:
    def test_one_rectangle_per_line_tight_around_the_words_covered(self):
        content = "Bonjour tout le monde\nDeuxieme ligne"
        boxes = [
            _box(
                "Bonjour tout le monde",
                0.1,
                0.1,
                0.9,
                0.2,
                0,
                21,
                [_word("Bonjour", 0.1, 0.3, 0, 7), _word("tout", 0.32, 0.45, 8, 12), _word("le", 0.47, 0.5, 13, 15)],
            ),
            _box("Deuxieme ligne", 0.1, 0.3, 0.6, 0.4, 22, 36, [_word("Deuxieme", 0.1, 0.35, 22, 30)]),
        ]
        start = content.index("tout")

        rects = rects_for_span(boxes, start, content.index("Deuxieme") + 8)

        assert rects == [
            {"x_min": 0.32, "y_min": 0.1, "x_max": 0.5, "y_max": 0.2},
            {"x_min": 0.1, "y_min": 0.1, "x_max": 0.35, "y_max": 0.2},
        ]

    def test_a_line_without_words_is_framed_whole(self):
        assert rects_for_span([_box("Une ligne", 0.1, 0.5, 0.7, 0.6, 0, 9)], 2, 5) == [
            {"x_min": 0.1, "y_min": 0.5, "x_max": 0.7, "y_max": 0.6}
        ]

    def test_a_line_with_no_interval_is_left_out(self):
        """What OCR gives when the line could not be found in the content: it can be read, not placed."""
        assert rects_for_span([_box("Texte OCR", 0.1, 0.5, 0.7, 0.6, None, None)], 0, 50) == []

    def test_lines_the_interval_does_not_touch_are_left_out(self):
        boxes = [_box("a", 0.1, 0.1, 0.2, 0.2, 0, 10), _box("b", 0.1, 0.3, 0.2, 0.4, 10, 20)]

        assert rects_for_span(boxes, 10, 20) == [{"x_min": 0.1, "y_min": 0.3, "x_max": 0.2, "y_max": 0.4}]


class TestChunkPositions:
    SPANS = {"spans": [{"page": 4, "start": 120, "end": 560}, {"page": 3, "start": 900, "end": 1000}]}

    def test_the_pages_of_a_chunk_come_from_its_intervals_in_order(self):
        assert chunk_pages_of(self.SPANS) == [3, 4]

    def test_a_chunk_without_intervals_has_the_pages_between_its_first_and_last(self):
        assert chunk_pages_of({"page_start": 2, "page_end": 4}) == [2, 3, 4]
        assert chunk_pages_of({"page_start": 2, "page_end": 2}) == [2]

    def test_a_chunk_that_says_nothing_or_nonsense_has_no_known_pages(self):
        for extras in ({}, {"page_start": 5, "page_end": 2}, {"page_start": 1, "page_end": 400}, {"spans": []}):
            assert chunk_pages_of(extras) == []

    def test_the_intervals_of_a_chunk_on_a_page(self):
        assert chunk_spans_on(self.SPANS, 4, 2000) == [(120, 560)]
        assert chunk_spans_on(self.SPANS, 3, 2000) == [(900, 1000)]

    def test_an_interval_is_brought_back_into_the_content_and_dropped_when_nothing_is_left(self):
        assert chunk_spans_on(self.SPANS, 4, 300) == [(120, 300)]
        assert chunk_spans_on(self.SPANS, 4, 100) == []

    def test_none_means_the_chunk_has_no_intervals_and_empty_that_it_is_not_on_the_page(self):
        assert chunk_spans_on({"page_start": 1, "page_end": 1}, 1, 100) is None
        assert chunk_spans_on({"spans": []}, 1, 100) is None
        assert chunk_spans_on(self.SPANS, 9, 2000) == []
