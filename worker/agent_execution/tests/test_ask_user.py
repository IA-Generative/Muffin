import pytest

from app.ask_user import (
    ASK_USER_TOOL,
    NO_VALID_QUESTION,
    ask_user,
    free_text_question,
    question_rounds,
    render_questions,
    sanitize_questions,
)


def _question(**overrides):
    base = {
        "question": "Which period?",
        "header": "Period",
        "multi_select": False,
        "options": [{"label": "2023", "description": "Last year"}, {"label": "2024", "description": "This year"}],
    }
    base.update(overrides)
    return base


def test_a_valid_question_is_kept_as_it_is():
    assert sanitize_questions([_question()]) == [_question()]


def test_whitespace_is_normalised_and_texts_are_bounded():
    [question] = sanitize_questions(
        [_question(question="  Which \n  period ?  " + "x" * 400, header="A very long header indeed")]
    )

    assert question["question"].startswith("Which period ? xxx")
    assert len(question["question"]) == 300
    assert question["header"] == "A very long"


def test_a_missing_header_is_made_from_the_question():
    [question] = sanitize_questions([_question(header="")])

    assert question["header"] == "Which period"


def test_a_question_with_fewer_than_two_options_is_dropped():
    assert sanitize_questions([_question(options=[{"label": "only one"}])]) == []
    assert sanitize_questions([_question(options=[{"label": "a"}, {"label": "A"}, {"label": "  "}])]) == []


def test_options_are_cleaned_deduplicated_and_capped_at_four():
    options = [{"label": f"option {n}"} for n in range(7)] + [{"label": "OPTION 0"}, "junk", 3]

    [question] = sanitize_questions([_question(options=options)])

    assert [option["label"] for option in question["options"]] == [f"option {n}" for n in range(4)]
    assert question["options"][0]["description"] == ""


def test_a_question_with_no_text_is_dropped_and_at_most_four_are_kept():
    questions = sanitize_questions([_question(question=" ")] + [_question(question=f"Q{n}?") for n in range(6)])

    assert [question["question"] for question in questions] == ["Q0?", "Q1?", "Q2?"]
    assert len(sanitize_questions([_question(question=f"Q{n}?") for n in range(6)])) == 4


@pytest.mark.parametrize("raw", [None, "a string", 3, {}, [None, 3, "x", {}]])
def test_anything_that_is_not_a_list_of_questions_gives_none(raw):
    assert sanitize_questions(raw) == []


def test_multi_select_is_only_true_when_it_says_so():
    assert sanitize_questions([_question(multi_select="yes")])[0]["multi_select"] is False
    assert sanitize_questions([_question(multi_select=True)])[0]["multi_select"] is True


def test_the_tool_answers_the_model_instead_of_interrupting_when_nothing_is_valid():
    assert ask_user({"questions": [_question(options=[])]}) == ([], NO_VALID_QUESTION)
    assert ask_user("not even a dict") == ([], NO_VALID_QUESTION)
    questions, error = ask_user({"questions": [_question()]})
    assert error is None and len(questions) == 1


def test_the_tool_tells_the_model_to_ask_only_when_it_changes_the_result():
    description = ASK_USER_TOOL["function"]["description"]

    assert "really changes" in description and "Write nothing else after asking" in description
    assert ASK_USER_TOOL["function"]["parameters"]["properties"]["questions"]["maxItems"] == 4


def test_questions_are_rendered_as_text_for_the_thread():
    text = render_questions(
        [_question(), _question(question="Which services?", options=[{"label": "HR"}, {"label": "IT"}])]
    )

    assert text == "Which period?\n- 2023 : Last year\n- 2024 : This year\n\nWhich services?\n- HR\n- IT"


def test_a_free_text_question_has_no_options():
    assert render_questions([free_text_question("  What do you   mean ? ")]) == "What do you mean ?"


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([], 0),
        ([{"role": "user"}, {"role": "assistant"}], 0),
        ([{"role": "assistant", "asked": True}, {"role": "user"}], 1),
        (
            [
                {"role": "assistant", "asked": True},
                {"role": "user"},
                {"role": "assistant", "asked": True},
                {"role": "user"},
            ],
            2,
        ),
        # An answered question followed by a normal answer starts the count again.
        ([{"role": "assistant", "asked": True}, {"role": "user"}, {"role": "assistant"}, {"role": "user"}], 0),
        ([{"role": "assistant"}, {"role": "user"}, {"role": "assistant", "asked": True}, {"role": "user"}], 1),
    ],
)
def test_the_rounds_of_questions_in_a_row_are_counted_from_the_end(history, expected):
    assert question_rounds(history) == expected
