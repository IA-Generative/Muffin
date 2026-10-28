"""The citations of an answer: the markers `[evidence id]` the model writes in it, checked against its excerpts.

A claim is attached to its source by a marker, and the interface builds its sources from the markers alone. The model is
asked to write them, which is only a request: nothing else made sure that it did, that the ids were real, or that an
overridden (administrable) prompt kept the request (#402). This is the check, on what the model wrote."""

import re

# Whatever the model is asked, from the code and not from the prompt - which is administrable and may lose it.
CITATION_RULE = (
    "\n\nCitations (mandatory): every claim drawn from the evidence ends with the id of the excerpt it comes from, in "
    "square brackets exactly as given, e.g. [0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a]. Several ids in a row each get "
    "their own brackets. Only use ids that appear in the evidence. An answer with no citation is rejected."
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


def without_invented_markers(answer: str, valid_ids: set[str]) -> str:
    """The answer without the citations that point to nothing: an id the model made up is dropped from its bracket,
    and a bracket left empty goes with its space."""

    def keep(match: re.Match[str]) -> str:
        kept = [candidate for candidate in _ids_of(match.group(2)) if candidate in valid_ids]
        return match.group(1) + "".join(f"[{candidate}]" for candidate in kept) if kept else ""

    return _MARKER_AFTER_SPACE.sub(keep, answer)


RETRY_MESSAGE = (
    "Your answer cites none of the evidence excerpts. Write it again: same content, but every claim drawn from the "
    "evidence must end with the id of its excerpt in square brackets, as given at the start of each excerpt. "
    "Answer only with the rewritten answer."
)
