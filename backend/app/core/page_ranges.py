"""A list of page ranges typed by a person: "1-5, 40-45, 90-" - what a collection may ask its summary to read (#372).

`a` is one page, `a-b` pages a to b, `a-` page a to the end. The worker has the same parser (app/sampling.py), the
same cases are tested on both sides."""

import re

_RANGE = re.compile(r"^(\d+)(?:(-)(\d*))?$")


class InvalidPageRangesError(ValueError):
    pass


def parse_page_ranges(text: str) -> list[tuple[int, int | None]]:
    """[(first, last)] - last None for "to the end". Raises InvalidPageRangesError on anything else."""
    ranges: list[tuple[int, int | None]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        found = _RANGE.match(re.sub(r"\s*-\s*", "-", part))
        if not found:
            raise InvalidPageRangesError(f"'{part}' is not a page or a range of pages")
        first = int(found.group(1))
        last = (int(found.group(3)) if found.group(3) else None) if found.group(2) else first
        if first < 1 or (last is not None and last < first):
            raise InvalidPageRangesError(f"'{part}' is not a range of pages")
        ranges.append((first, last))
    return ranges
