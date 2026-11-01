"""The citations of an answer: the markers `[evidence id]` the model writes in it and the passages it names, checked
against its excerpts.

A claim is attached to its source by a marker, and the interface builds its sources from the markers alone. The model is
asked to write them, which is only a request: nothing else made sure that it did, that the ids were real, or that an
overridden (administrable) prompt kept the request (#402). This is the check, on what the model wrote."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Whatever the model is asked, from the code and not from the prompt - which is administrable and may lose it.
CITATION_RULE = (
    "\n\nCitations (mandatory): every claim drawn from the evidence ends with the id of the excerpt it comes from, in "
    "square brackets exactly as given, e.g. [0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a]. Several ids in a row each get "
    "their own brackets. Only use ids that appear in the evidence. An answer with no citation is rejected."
)

# What the model is asked to write (#402): the answer first, so that it can be shown as it comes, then the excerpts
# it used with the passage of each, copied word for word. The worker never keeps the model's copy: it keeps the text
# of the excerpt itself, found by the id and the passage (resolve_passages).
OUTPUT_FORMAT = (
    '\n\nFormat: reply with ONE JSON object and nothing else: {"answer": "<the answer, markdown, with the [id] '
    'citations>", "sources": [{"id": "<id of an excerpt you used>", "quote": "<the passage of that excerpt that '
    'supports the answer, copied word for word, 300 characters at most>"}]}. Write "answer" first. List each excerpt '
    "you cite once, with a passage that is really in it."
)

# The same shape as the interface reads (useChat.ts, formatAnswerWithCitations): a bracket of hexadecimal ids, possibly
# several, separated by commas, semicolons or spaces.
_MARKER = re.compile(r"\[([0-9a-f][0-9a-f,;\s-]{6,}[0-9a-f])\]", re.IGNORECASE)
_MARKER_AFTER_SPACE = re.compile(r"([ \t]?)" + _MARKER.pattern, re.IGNORECASE)
_SEPARATORS = re.compile(r"[,;\s]+")


def _ids_of(group: str) -> list[str]:
    return [candidate.strip() for candidate in _SEPARATORS.split(group) if candidate.strip()]


def cited_ids(answer: str, valid_ids: set[str]) -> list[str]:
    """The ids of the excerpts the answer cites, in the order it cites them. An id that is not one of the excerpts is
    not a citation."""
    found: dict[str, None] = {}
    for match in _MARKER.finditer(answer):
        for candidate in _ids_of(match.group(1)):
            if candidate in valid_ids:
                found[candidate] = None
    return list(found)


def replace_markers(text: str, render: Callable[[list[str]], str]) -> str:
    """The text with each bracket of citations replaced by what `render` makes of the ids in it, in order - for a
    client that does not know the interface's markers (the OpenAI-compatible API numbers them, #513)."""
    return _MARKER.sub(lambda match: render(_ids_of(match.group(1))), text)


def without_invented_markers(answer: str, valid_ids: set[str]) -> str:
    """The answer without the citations that point to nothing: an id the model made up is dropped from its bracket,
    and a bracket left empty goes with its space."""

    def keep(match: re.Match[str]) -> str:
        kept = [candidate for candidate in _ids_of(match.group(2)) if candidate in valid_ids]
        return match.group(1) + "".join(f"[{candidate}]" for candidate in kept) if kept else ""

    return _MARKER_AFTER_SPACE.sub(keep, answer)


RETRY_MESSAGE = (
    "Your answer cites none of the evidence excerpts. Write it again: same content, but every claim drawn from the "
    "evidence must end with the id of its excerpt in square brackets, as given at the start of each excerpt, and "
    '"sources" must list the excerpts used. Answer only with the JSON object, as asked.'
)


# --- the structured answer ---

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*")
_ANSWER_KEY = re.compile(r'"answer"\s*:\s*"')
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def partial_answer(raw: str) -> str:
    """The answer written so far, for the chat to show while the rest comes: the text of the "answer" field of the
    JSON the model is writing, decoded up to where it has got - or the raw text if it is not writing JSON at all."""
    text = _FENCE.sub("", raw, count=1)
    if not text.lstrip().startswith("{"):
        return raw
    start = _ANSWER_KEY.search(text)
    if start is None:
        return ""
    out: list[str] = []
    i = start.end()
    while i < len(text):
        char = text[i]
        if char == '"':
            break
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 >= len(text):
            break  # an escape cut in two: its end is not here yet
        code = text[i + 1]
        if code == "u":
            digits = text[i + 2 : i + 6]
            if len(digits) < 4:
                break
            try:
                out.append(chr(int(digits, 16)))
            except ValueError:
                pass
            i += 6
            continue
        out.append(_ESCAPES.get(code, code))
        i += 2
    return "".join(out)


def parse_answer(raw: str) -> tuple[str, list[dict[str, Any]]]:
    """(answer, sources) from what the model wrote. A model that wrote plain text, or JSON that is not what was asked,
    has its whole text taken as the answer, with no sources: the markers in it are then all there is to go by."""
    text = _FENCE.sub("", raw.strip(), count=1).removesuffix("```").strip()
    candidates = [text]
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
            sources = parsed.get("sources")
            return parsed["answer"], [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []
    return raw, []


# --- the passages ---

MIN_QUOTE_CHARS = 12
_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u00ab": '"', "\u00bb": '"'})


@dataclass(frozen=True)
class Passage:
    """The passage a citation rests on, as it is in the excerpt: the text of the excerpt itself and where it is."""

    text: str
    start: int
    end: int


def _normalized(text: str) -> tuple[str, list[int]]:
    """The text as comparable - lower case, one space for any run of white space, one kind of quotes, hyphenation at
    the end of a line undone - and, for each of its characters, where it comes from in the text."""
    chars: list[str] = []
    origin: list[int] = []
    previous_space = True
    i = 0
    while i < len(text):
        char = text[i]
        if char == "-" and i + 1 < len(text) and text[i + 1] == "\n" and chars and chars[-1].isalpha():
            i += 2  # "informa-\ntion" is "information"
            continue
        if char in "\u00ad\u200b":
            i += 1
            continue
        if char.isspace():
            if not previous_space:
                chars.append(" ")
                origin.append(i)
            previous_space = True
            i += 1
            continue
        previous_space = False
        folded = char.translate(_QUOTES).casefold()
        for piece in folded:
            chars.append(piece)
            origin.append(i)
        i += 1
    return "".join(chars), origin


def find_passage(quote: str, content: str) -> Passage | None:
    """Where `quote` is in `content`, if it is: the passage as the excerpt has it. The model copies, and copying loses
    white space, a hyphen at the end of a line, the kind of quotes - none of which makes it another passage - but a word
    changed does, and then there is no passage."""
    wanted, _ = _normalized(quote)
    wanted = wanted.strip()
    if len(wanted) < MIN_QUOTE_CHARS:
        return None
    haystack, origin = _normalized(content)
    at = haystack.find(wanted)
    if at < 0:
        return None
    start, end = origin[at], origin[at + len(wanted) - 1] + 1
    return Passage(content[start:end], start, end)


def resolve_passages(sources: list[dict[str, Any]], excerpts: list[dict[str, Any]]) -> dict[str, Passage | None]:
    """For each excerpt the model named, the passage it rests on - or None when the passage it gave is not in the
    excerpt. An id that is not an excerpt is dropped. The first passage given for an id is the one that counts."""
    by_id = {excerpt["id"]: excerpt for excerpt in excerpts}
    resolved: dict[str, Passage | None] = {}
    for source in sources:
        id_ = source.get("id")
        if not isinstance(id_, str) or id_ not in by_id:
            continue
        quote = source.get("quote")
        passage = find_passage(quote, by_id[id_]["content"]) if isinstance(quote, str) else None
        if id_ not in resolved or (resolved[id_] is None and passage is not None):
            resolved[id_] = passage
    return resolved
