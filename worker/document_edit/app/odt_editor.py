"""Applies typed operations (app/operations.py) to an ODT file, in place (#168).

The file is never regenerated: its content.xml is edited through odfdo and written back, so
everything an operation doesn't name - styles, images, footnotes, tables of contents, lists - is
carried over untouched. New content borrows the styles already used by its neighbours, so an
addition looks like the rest of the document.

All-or-nothing: operations run on an in-memory copy and the result is only serialised once every
one of them has been applied. A failing operation raises OperationError naming which one."""

import io
from collections import Counter
from dataclasses import dataclass

from odfdo import Cell, Document, Header, Paragraph, Row, Table

from app.operations import (
    DeleteColumn,
    DeleteParagraph,
    DeleteRow,
    InsertColumn,
    InsertParagraph,
    InsertRow,
    InsertSection,
    InsertTable,
    Operation,
    ReplaceParagraph,
    SectionRef,
    SetCell,
    TableRef,
)

_PARAGRAPH = "text:p"
_TABLE = "table:table"
_NUMERIC_CELL_TYPES = {"float", "percentage", "currency"}


class OperationError(Exception):
    """An operation can't be applied. `index` is its 1-based position in the list, `message` is
    meant to be read as-is - by the user, or fed back to the model that wrote the operation."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"Opération {index} : {message}")
        self.index = index
        self.message = message


class _Refused(Exception):
    """Raised inside an operation, wrapped into an OperationError with its index by the caller."""


@dataclass
class EditResult:
    data: bytes
    # One human-readable line per applied operation, in order.
    summary: list[str]


@dataclass
class _Span:
    """The body children of a section: [start, end) in body.children."""

    start: int
    end: int
    label: str


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _text_of(element) -> str:
    return element.text_recursive.strip()


def _repeated(element) -> int:
    return element.repeated or 1


class _Editor:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.body = document.body

    # -- structure ---------------------------------------------------------------------------

    def _children(self) -> list:
        return list(self.body.children)

    def _headings(self, children: list) -> list[int]:
        return [i for i, child in enumerate(children) if isinstance(child, Header)]

    def _section(self, ref: SectionRef) -> _Span:
        children = self._children()
        headings = self._headings(children)
        if ref.heading is None:
            return _Span(0, headings[0] if headings else len(children), "le début du document")

        wanted = _normalise(ref.heading)
        matches = [i for i in headings if _normalise(_text_of(children[i])) == wanted]
        if len(matches) < ref.occurrence:
            available = ", ".join(f"« {_text_of(children[i])} »" for i in headings) or "aucun titre"
            raise _Refused(f"titre « {ref.heading} » introuvable (occurrence {ref.occurrence}). Titres : {available}.")
        start = matches[ref.occurrence - 1]
        later = [i for i in headings if i > start]
        return _Span(start + 1, later[0] if later else len(children), f"« {ref.heading} »")

    def _block_end(self, children: list, heading_index: int) -> int:
        """End of a heading's whole block: up to the next heading of the same or a higher level,
        so a new sibling section lands after the subsections rather than between them."""
        level = int(children[heading_index].level)
        for i in range(heading_index + 1, len(children)):
            if isinstance(children[i], Header) and int(children[i].level) <= level:
                return i
        return len(children)

    def _paragraphs(self, children: list, span: _Span) -> list[tuple[int, object]]:
        return [(i, children[i]) for i in range(span.start, span.end) if children[i].tag == _PARAGRAPH]

    def _paragraph(self, ref: SectionRef, number: int) -> tuple[_Span, object]:
        span = self._section(ref)
        paragraphs = self._paragraphs(self._children(), span)
        if number > len(paragraphs):
            raise _Refused(f"{span.label} n'a que {len(paragraphs)} paragraphe(s), pas de paragraphe {number}.")
        return span, paragraphs[number - 1][1]

    def _insert_position(self, span: _Span, after_paragraph: int | None) -> int:
        children = self._children()
        if after_paragraph is None:
            return span.end
        if after_paragraph == 0:
            return span.start
        paragraphs = self._paragraphs(children, span)
        if after_paragraph > len(paragraphs):
            raise _Refused(
                f"{span.label} n'a que {len(paragraphs)} paragraphe(s), "
                f"impossible d'insérer après le {after_paragraph}."
            )
        return paragraphs[after_paragraph - 1][0] + 1

    def _table(self, ref: TableRef) -> Table:
        span = self._section(ref.section)
        children = self._children()
        tables = [children[i] for i in range(span.start, span.end) if children[i].tag == _TABLE]
        if ref.index > len(tables):
            raise _Refused(f"{span.label} contient {len(tables)} tableau(x), pas de tableau {ref.index}.")
        return tables[ref.index - 1]

    # -- styles ------------------------------------------------------------------------------

    def _body_paragraph_style(self, children: list, before: int | None = None) -> str | None:
        """Style for a paragraph added at body level: the nearest paragraph above (else below)
        the insertion point, else the document's most common paragraph style."""
        paragraphs = [(i, c) for i, c in enumerate(children) if c.tag == _PARAGRAPH]
        if before is not None:
            above = [c for i, c in paragraphs if i < before]
            below = [c for i, c in paragraphs if i >= before]
            for candidate in above[-1:] + below[:1]:
                if candidate.style:
                    return candidate.style
        styles = Counter(c.style for _, c in paragraphs if c.style)
        return styles.most_common(1)[0][0] if styles else None

    def _heading_style(self, children: list, level: int) -> str | None:
        headings = [children[i] for i in self._headings(children)]
        for heading in headings:
            # odfdo hands the outline level back as a string.
            if int(heading.level) == level and heading.style:
                return heading.style
        return self._named_style(f"Heading_20_{level}")

    def _named_style(self, name: str) -> str | None:
        return name if self.document.get_style("paragraph", name) is not None else None

    # -- cell helpers ------------------------------------------------------------------------

    @staticmethod
    def _cell_paragraph_style(cell: Cell) -> str | None:
        paragraphs = cell.get_paragraphs()
        return paragraphs[0].style if paragraphs else None

    @staticmethod
    def _write_cell(cell: Cell, text: str, paragraph_style: str | None) -> None:
        """Sets a cell's text, keeping the paragraph style its content had. A numeric cell given a
        number stays numeric; anything else becomes a plain string."""
        value: str | float = text
        if cell.get_attribute("office:value-type") in _NUMERIC_CELL_TYPES:
            try:
                value = float(text.replace(",", "."))
            except ValueError:
                value = text
        cell.set_value(value)
        if paragraph_style:
            for paragraph in cell.get_paragraphs():
                paragraph.style = paragraph_style

    @staticmethod
    def _check_in_table(table: Table, row: int | None = None, column: int | None = None) -> None:
        rows, columns = len(table.get_rows()), table.width
        if row is not None and row > rows:
            raise _Refused(f"le tableau n'a que {rows} ligne(s), pas de ligne {row}.")
        if column is not None and column > columns:
            raise _Refused(f"le tableau n'a que {columns} colonne(s), pas de colonne {column}.")

    # -- operations --------------------------------------------------------------------------

    def apply(self, operation: Operation) -> str:
        handler = {
            "replace_paragraph": self._replace_paragraph,
            "insert_paragraph": self._insert_paragraph,
            "delete_paragraph": self._delete_paragraph,
            "insert_section": self._insert_section,
            "set_cell": self._set_cell,
            "insert_row": self._insert_row,
            "delete_row": self._delete_row,
            "insert_column": self._insert_column,
            "delete_column": self._delete_column,
            "insert_table": self._insert_table,
        }[operation.op]
        return handler(operation)

    def _replace_paragraph(self, op: ReplaceParagraph) -> str:
        span, paragraph = self._paragraph(op.section, op.paragraph)
        # clear() drops the element's attributes too - put them back so the paragraph keeps its
        # style (and anything else the document attached to it). Inline formatting of the old
        # text (bold, links) is replaced along with the text.
        attributes = dict(paragraph.attributes)
        paragraph.clear()
        for name, value in attributes.items():
            paragraph.set_attribute(name, value)
        paragraph.append(op.text)
        return f"Paragraphe {op.paragraph} de {span.label} remplacé."

    def _insert_paragraph(self, op: InsertParagraph) -> str:
        span = self._section(op.section)
        position = self._insert_position(span, op.after_paragraph)
        style = self._body_paragraph_style(self._children(), before=position)
        self.body.insert(Paragraph(op.text, style=style), position=position)
        where = "à la fin" if op.after_paragraph is None else f"après le paragraphe {op.after_paragraph}"
        return f"Paragraphe ajouté {where} de {span.label}."

    def _delete_paragraph(self, op: DeleteParagraph) -> str:
        span, paragraph = self._paragraph(op.section, op.paragraph)
        self.body.delete(paragraph)
        return f"Paragraphe {op.paragraph} de {span.label} supprimé."

    def _insert_section(self, op: InsertSection) -> str:
        children = self._children()
        if op.after is None:
            position, where = len(children), "à la fin du document"
        else:
            span = self._section(op.after)
            if op.after.heading is None:
                position, where = span.end, "après le début du document"
            else:
                position = self._block_end(children, span.start - 1)
                where = f"après la section {span.label}"
        heading = Header(op.level, op.title)
        # Header ignores its `style` constructor argument - it has to be set afterwards.
        heading_style = self._heading_style(children, op.level)
        if heading_style:
            heading.style = heading_style
        self.body.insert(heading, position=position)
        body_style = self._body_paragraph_style(children, before=position)
        for offset, text in enumerate(op.paragraphs, start=1):
            self.body.insert(Paragraph(text, style=body_style), position=position + offset)
        return f"Section « {op.title} » (niveau {op.level}) ajoutée {where}."

    def _set_cell(self, op: SetCell) -> str:
        table = self._table(op.table)
        self._check_in_table(table, row=op.row, column=op.column)
        cell = table.get_cell((op.column - 1, op.row - 1))
        self._write_cell(cell, op.text, self._cell_paragraph_style(cell))
        table.set_cell((op.column - 1, op.row - 1), cell)
        return f"Cellule (ligne {op.row}, colonne {op.column}) modifiée."

    def _insert_row(self, op: InsertRow) -> str:
        table = self._table(op.table)
        rows, width = len(table.get_rows()), table.width
        after = rows if op.after_row is None else op.after_row
        if after > rows:
            raise _Refused(f"le tableau n'a que {rows} ligne(s), impossible d'insérer après la ligne {after}.")
        if len(op.values) > width:
            raise _Refused(f"{len(op.values)} valeurs pour un tableau de {width} colonne(s).")
        # Format like a data row, not the header: the row above the insertion point, unless that
        # is the header (row 1) and there is another row to copy.
        reference = after if after >= 2 or rows < 2 else 2
        reference = max(1, min(reference, rows))
        new_row: Row = table.get_row(reference - 1).clone
        # A copy of a "repeated" row would stand for several rows - it must be a single one.
        new_row.repeated = None
        for index in range(width):
            cell = new_row.get_cell(index)
            self._write_cell(cell, op.values[index] if index < len(op.values) else "", self._cell_paragraph_style(cell))
            new_row.set_cell(index, cell)
        table.insert_row(after, new_row)
        return f"Ligne ajoutée après la ligne {after} du tableau."

    def _delete_row(self, op: DeleteRow) -> str:
        table = self._table(op.table)
        self._check_in_table(table, row=op.row)
        if len(table.get_rows()) == 1:
            raise _Refused("impossible de supprimer la dernière ligne du tableau.")
        table.delete_row(op.row - 1)
        return f"Ligne {op.row} du tableau supprimée."

    def _insert_column(self, op: InsertColumn) -> str:
        table = self._table(op.table)
        rows, width = len(table.get_rows()), table.width
        after = width if op.after_column is None else op.after_column
        if after > width:
            raise _Refused(f"le tableau n'a que {width} colonne(s), impossible d'insérer après la colonne {after}.")
        if len(op.values) > rows:
            raise _Refused(f"{len(op.values)} valeurs pour un tableau de {rows} ligne(s).")
        table.insert_column(after)
        # New cells are formatted like the column they were added next to: the one on their left,
        # or - added at the far left - the old first column, which has moved one to the right.
        reference = 1 if after == 0 else after - 1
        for row in range(rows):
            source = table.get_cell((reference, row))
            cell = table.get_cell((after, row))
            cell.style = source.style
            text = op.values[row] if row < len(op.values) else ""
            self._write_cell(cell, text, self._cell_paragraph_style(source))
            table.set_cell((after, row), cell)
        return f"Colonne ajoutée après la colonne {after} du tableau."

    def _delete_column(self, op: DeleteColumn) -> str:
        table = self._table(op.table)
        self._check_in_table(table, column=op.column)
        if table.width == 1:
            raise _Refused("impossible de supprimer la dernière colonne du tableau.")
        table.delete_column(op.column - 1)
        return f"Colonne {op.column} du tableau supprimée."

    def _insert_table(self, op: InsertTable) -> str:
        span = self._section(op.section)
        position = self._insert_position(span, op.after_paragraph)
        width = len(op.rows[0])
        if any(len(row) != width for row in op.rows):
            raise _Refused("toutes les lignes du tableau doivent avoir le même nombre de cellules.")

        children = self._children()
        existing = next((c for c in children if c.tag == _TABLE), None)
        table_style = existing.style if existing is not None else None
        header_style = body_style = None
        if existing is not None:
            rows = existing.get_rows()
            header_style = self._cell_paragraph_style(rows[0].get_cell(0))
            body_style = self._cell_paragraph_style(rows[min(1, len(rows) - 1)].get_cell(0))
        name = self._free_table_name(children)
        table = Table(name, width=width, height=len(op.rows), style=table_style)
        for r, values in enumerate(op.rows):
            for c, text in enumerate(values):
                cell = table.get_cell((c, r))
                self._write_cell(cell, text, header_style if r == 0 else body_style)
                table.set_cell((c, r), cell)
        self.body.insert(table, position=position)
        return f"Tableau de {len(op.rows)} ligne(s) et {width} colonne(s) ajouté dans {span.label}."

    @staticmethod
    def _free_table_name(children: list) -> str:
        used = {c.name for c in children if c.tag == _TABLE}
        number = len(used) + 1
        while f"Tableau{number}" in used:
            number += 1
        return f"Tableau{number}"


def apply_operations(source: bytes, operations: list[Operation]) -> EditResult:
    """Returns the edited ODT and one summary line per operation. Raises OperationError - naming
    the failing operation - without producing anything if any of them can't be applied."""
    editor = _Editor(Document(io.BytesIO(source)))
    summary: list[str] = []
    for index, operation in enumerate(operations, start=1):
        try:
            summary.append(editor.apply(operation))
        except _Refused as refusal:
            raise OperationError(index, str(refusal)) from refusal
    buffer = io.BytesIO()
    editor.document.save(buffer)
    return EditResult(data=buffer.getvalue(), summary=summary)
