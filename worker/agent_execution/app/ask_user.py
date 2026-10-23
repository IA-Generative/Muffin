"""The assistant's multiple-choice questions (#344): what the model may ask, cleaned before anyone sees it.

The model proposes 1 to 4 questions with 2 to 4 options each, when a precision really changes the answer
and is not in the documents. What it writes is never trusted as is: texts are bounded and whitespace is
normalised, a question with fewer than two usable options is dropped. The questions are then kept with the
assistant's message (the thread is the state, nothing waits), the user answers whenever they want, and the
answer reaches the next run through the conversation."""

from typing import Any

MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_QUESTION_LENGTH = 300
MAX_HEADER_LENGTH = 12
MAX_LABEL_LENGTH = 60
MAX_DESCRIPTION_LENGTH = 120

# What the model is told about asking: only when a precision changes the result, and nothing else after.
GUIDANCE = (
    "Ask the user 1 to 4 multiple-choice questions instead of guessing, but only when the answer really changes "
    "the result and cannot be found in their documents. Each question is complete and ends with a question mark, "
    "has a short header (one or two words, 12 characters at most) and 2 to 4 options, each with a short label and "
    "a one-sentence description; set multi_select to true when several options can apply. Write them in the "
    "user's language. Write nothing else after asking."
)

# The tool a model that chooses its own tools is given (#343 builds that loop): same arguments, same cleaning.
ASK_USER_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": GUIDANCE,
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_QUESTIONS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "header": {"type": "string", "maxLength": MAX_HEADER_LENGTH},
                            "multi_select": {"type": "boolean"},
                            "options": {
                                "type": "array",
                                "minItems": MIN_OPTIONS,
                                "maxItems": MAX_OPTIONS,
                                "items": {
                                    "type": "object",
                                    "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
                                    "required": ["label"],
                                },
                            },
                        },
                        "required": ["question", "options"],
                    },
                }
            },
            "required": ["questions"],
        },
    },
}

# What the model is told when it asked nothing usable - it carries on rather than the discussion stopping.
NO_VALID_QUESTION = (
    "Give 1 to 4 questions, each with a question text and 2 to 4 options with a label - fix the arguments, "
    "or continue without asking."
)
NOBODY_TO_ASK = (
    "Nobody can answer questions here: continue with the most reasonable assumptions, and state them in the answer."
)


def _text(value: Any, limit: int) -> str:
    """Whitespace normalised, bounded."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _options(raw: Any) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"), MAX_LABEL_LENGTH)
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        options.append({"label": label, "description": _text(item.get("description"), MAX_DESCRIPTION_LENGTH)})
    return options[:MAX_OPTIONS]


def sanitize_questions(raw: Any) -> list[dict[str, Any]]:
    """The valid questions among what the model gave, cleaned: [] when none is."""
    questions: list[dict[str, Any]] = []
    for item in raw[:MAX_QUESTIONS] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question"), MAX_QUESTION_LENGTH)
        options = _options(item.get("options"))
        if not question or len(options) < MIN_OPTIONS:
            continue
        questions.append(
            {
                "question": question,
                "header": _text(item.get("header"), MAX_HEADER_LENGTH) or _text(question, MAX_HEADER_LENGTH),
                "multi_select": item.get("multi_select") is True,
                "options": options,
            }
        )
    return questions


def free_text_question(text: str) -> dict[str, Any]:
    """A question the model gave no options for: answered in free text only."""
    return {
        "question": _text(text, MAX_QUESTION_LENGTH),
        "header": "Précision",
        "multi_select": False,
        "options": [],
    }


def ask_user(arguments: Any) -> tuple[list[dict[str, Any]], str | None]:
    """The `ask_user` tool call: (questions, None) when there is something to ask, ([], what to tell the model)
    when its arguments hold no valid question."""
    questions = sanitize_questions(arguments.get("questions") if isinstance(arguments, dict) else None)
    return (questions, None) if questions else ([], NO_VALID_QUESTION)


def render_questions(questions: list[dict[str, Any]]) -> str:
    """The questions as text: what the thread, and so the next run's history, says the assistant asked."""
    blocks = []
    for question in questions:
        lines = [question["question"]]
        for option in question["options"]:
            description = f" : {option['description']}" if option.get("description") else ""
            lines.append(f"- {option['label']}{description}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def question_rounds(history: list[dict[str, Any]]) -> int:
    """How many times in a row the assistant asked questions, at the end of the history (an answer to each
    in between): what a cap on asking is counted against."""
    rounds = 0
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        if not message.get("asked"):
            break
        rounds += 1
    return rounds
