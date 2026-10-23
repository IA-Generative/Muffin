"""Where an entity is in the text of a window of pages (#352).

The model gives a name; the text says where it is. Each page of the window is searched for the name - the words in
order, separated by any whitespace, whatever the case, and as whole words (`Paris` is not in `Parisien`) - and what is
found is kept as intervals of characters of that page's content: what frames it on the page, through the boxes of the
page's lines (#350). A name found nowhere (the model normalized or translated it) has no occurrence, and nothing is
made up for it."""

import re

# Per page and per entity: a name that is everywhere (a common first name, a year) would drown the page in frames.
MAX_PER_PAGE = 10
MIN_NAME_LENGTH = 2


def find_mentions(content: str, name: str, limit: int = MAX_PER_PAGE) -> list[tuple[int, int]]:
    """The places of `name` in `content`, in order, up to `limit`."""
    words = name.split()
    if not content or len(name.strip()) < MIN_NAME_LENGTH:
        return []
    pattern = re.compile(r"(?<!\w)" + r"\s+".join(re.escape(word) for word in words) + r"(?!\w)", re.IGNORECASE)
    spans = []
    for match in pattern.finditer(content):
        spans.append(match.span())
        if len(spans) >= limit:
            break
    return spans
