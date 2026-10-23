from pydantic import BaseModel, Field

# What the worker sanitizes the model's questions down to (worker/agent_execution/app/ask_user.py), with
# a little room: these are the bounds a value is refused beyond, not the ones the model is held to.
MAX_QUESTIONS = 4
MAX_OPTIONS = 4


class QuestionOption(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=400)
    # A word or two, the tab the question gets in the interface.
    header: str = Field(min_length=1, max_length=24)
    multi_select: bool = False
    # None for a question that is only answered in free text (a clarification the model gave no choices to).
    options: list[QuestionOption] = Field(default_factory=list, max_length=MAX_OPTIONS)


class QuestionAnswer(BaseModel):
    """The answer to one question: options picked (labels), and/or free text."""

    selected: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    text: str | None = Field(default=None, max_length=2000)


class InvalidAnswersError(ValueError):
    """The answers do not fit the questions that were asked."""


def validate_answers(questions: list[dict], answers: list[QuestionAnswer]) -> list[QuestionAnswer]:
    """One answer per question, picking only labels that were offered (one at most for a single-choice
    question), each answered - by an option or by text. Returns the answers with blanks trimmed."""
    if len(answers) != len(questions):
        raise InvalidAnswersError("one answer is expected per question")
    cleaned = []
    for question, answer in zip(questions, answers, strict=True):
        offered = {option["label"] for option in question.get("options") or []}
        if any(label not in offered for label in answer.selected):
            raise InvalidAnswersError("an option that was not offered was picked")
        if len(set(answer.selected)) != len(answer.selected):
            raise InvalidAnswersError("an option was picked twice")
        if len(answer.selected) > 1 and not question.get("multi_select"):
            raise InvalidAnswersError("several options were picked for a single-choice question")
        text = (answer.text or "").strip() or None
        if not answer.selected and text is None:
            raise InvalidAnswersError("a question was left unanswered")
        cleaned.append(QuestionAnswer(selected=answer.selected, text=text))
    return cleaned
