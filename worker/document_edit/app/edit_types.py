"""What every applier (ODT, Markdown) hands back or raises - kept apart from them so the two
share it without importing each other."""

from dataclasses import dataclass


class OperationError(Exception):
    """An operation can't be applied. `index` is its 1-based position in the list, `message` is
    meant to be read as-is - by the user, or fed back to the model that wrote the operation."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"Opération {index} : {message}")
        self.index = index
        self.message = message


class Refused(Exception):
    """Raised inside an operation, wrapped into an OperationError with its index by the caller."""


@dataclass
class EditResult:
    data: bytes
    # One human-readable line per applied operation, in order.
    summary: list[str]


# Longest paragraph / table cell shown in an outline - enough to recognise and rewrite a paragraph,
# without one huge block eating the model's context.
_MAX_PARAGRAPH_CHARS = 1500
_MAX_CELL_CHARS = 80
_MAX_TABLE_ROWS_SHOWN = 40


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class OutlineSection:
    """One section of a document as the editing agent sees it. `items` are already rendered, one
    entry per block, in document order."""

    heading: str | None
    level: int
    # Which heading with that text this is (1-based) - what an operation's `occurrence` refers to.
    occurrence: int
    items: list[str]


def paragraph_item(number: int, text: str) -> str:
    return f"  ¶{number} {clip(text, _MAX_PARAGRAPH_CHARS)}"


def table_item(number: int, rows: list[list[str]]) -> str:
    width = max((len(row) for row in rows), default=0)
    lines = [f"  Tableau {number} ({len(rows)} ligne(s) × {width} colonne(s)) :"]
    for index, row in enumerate(rows[:_MAX_TABLE_ROWS_SHOWN], start=1):
        lines.append(f"    L{index}: " + " | ".join(clip(cell, _MAX_CELL_CHARS) for cell in row))
    if len(rows) > _MAX_TABLE_ROWS_SHOWN:
        lines.append(f"    … ({len(rows) - _MAX_TABLE_ROWS_SHOWN} ligne(s) de plus)")
    return "\n".join(lines)


def render_outline(sections: list[OutlineSection]) -> str:
    """The text the model reads: sections with their numbered paragraphs and tables, which is
    exactly the numbering the operations use to designate a target."""
    blocks = []
    for section in sections:
        if section.heading is None:
            if not section.items:
                continue
            title = "## Début du document (avant le premier titre)"
        else:
            title = f"## « {section.heading} » (niveau {section.level}, occurrence {section.occurrence})"
        blocks.append("\n".join([title, *(section.items or ["  (section vide)"])]))
    return "\n\n".join(blocks) or "(document vide)"
