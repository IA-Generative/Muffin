"""Applies typed operations (app/operations.py) to a Markdown file (#168) - the same vocabulary as
the ODT applier, so the agent doesn't care which format it is editing.

Edits are made on the source lines, located through markdown-it's block map: everything an
operation doesn't name stays byte for byte as it was (other paragraphs, lists, code fences, quotes,
HTML, front matter). Only a table an operation targets is re-rendered, as a plain GFM pipe table.

A "paragraph" is a top-level paragraph block - list items, code and quotes are not counted, same as
the ODT side. In a table the first row is the header: inserting above it or deleting it is refused,
since it would silently turn another row into the header."""

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

from app.edit_types import (
    EditResult,
    OperationError,
    OutlineSection,
    Refused,
    paragraph_item,
    render_outline,
    table_item,
)
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

_PARSER = MarkdownIt("commonmark").enable("table")
_OTHER = "  [bloc non modifiable (liste, code, citation ou HTML) : aucune opération ne peut le viser]"
_ALIGNMENT = re.compile(r"^\s*:?-+:?\s*$")


@dataclass
class _Block:
    kind: str  # "heading", "paragraph", "table" or "other"
    start: int  # first line
    end: int  # one past the last content line (trailing blank lines excluded)
    level: int = 0  # headings only


@dataclass
class _Span:
    """The blocks of a section: indices [start, end) into the block list, plus where the section
    begins and ends in the lines (`after_heading` is the line right under the heading)."""

    start: int
    end: int
    after_heading: int
    label: str


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _split_row(line: str) -> list[str]:
    """Cells of a pipe-table row; `\\|` is a literal pipe, not a separator."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", text)]


def _cell_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


@dataclass
class _TableModel:
    header: list[str]
    alignments: list[str]  # "", "left", "right" or "center", one per column
    rows: list[list[str]]

    @property
    def width(self) -> int:
        return len(self.header)

    @property
    def all_rows(self) -> list[list[str]]:
        return [self.header, *self.rows]

    @classmethod
    def parse(cls, lines: list[str]) -> "_TableModel":
        header = _split_row(lines[0])
        alignments = []
        for cell in _split_row(lines[1]):
            cell = cell.strip()
            left, right = cell.startswith(":"), cell.endswith(":")
            alignments.append("center" if left and right else "left" if left else "right" if right else "")
        rows = [_split_row(line) for line in lines[2:]]
        width = len(header)
        alignments = (alignments + [""] * width)[:width]
        # Ragged rows are tolerated by GFM; normalise so the model is rectangular.
        return cls(header, alignments, [(row + [""] * width)[:width] for row in rows])

    def render(self) -> list[str]:
        cells = [[_cell_text(c) for c in row] for row in self.all_rows]
        widths = [max(3, *(len(row[i]) for row in cells)) for i in range(self.width)]

        def justify(cell: str, i: int) -> str:
            alignment = self.alignments[i]
            if alignment == "right":
                return cell.rjust(widths[i])
            return cell.center(widths[i]) if alignment == "center" else cell.ljust(widths[i])

        def line(row: list[str]) -> str:
            return "| " + " | ".join(justify(cell, i) for i, cell in enumerate(row)) + " |"

        def rule(i: int) -> str:
            marks = {"": "-" * widths[i], "left": ":" + "-" * (widths[i] - 1), "right": "-" * (widths[i] - 1) + ":"}
            return marks.get(self.alignments[i], ":" + "-" * (widths[i] - 2) + ":")

        return [line(cells[0]), "| " + " | ".join(rule(i) for i in range(self.width)) + " |", *map(line, cells[1:])]


class _Editor:
    def __init__(self, text: str) -> None:
        # Edited as \n-separated lines; the original line ending is put back at the end.
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.replace("\r\n", "\n").split("\n")

    def text(self) -> str:
        return self.newline.join(self.lines)

    # -- structure ---------------------------------------------------------------------------

    def _blocks(self) -> list[_Block]:
        blocks: list[_Block] = []
        for token in _PARSER.parse("\n".join(self.lines)):
            if token.level != 0 or token.nesting == -1 or token.map is None:
                continue
            start, end = token.map
            while end > start + 1 and not self.lines[end - 1].strip():
                end -= 1  # a block's map can include its trailing blank lines (lists, for one)
            if token.type == "heading_open":
                blocks.append(_Block("heading", start, end, int(token.tag[1])))
            elif token.type == "paragraph_open":
                blocks.append(_Block("paragraph", start, end))
            elif token.type == "table_open":
                blocks.append(_Block("table", start, end))
            else:
                blocks.append(_Block("other", start, end))
        return blocks

    def _heading_text(self, block: _Block) -> str:
        line = self.lines[block.start]
        if block.end - block.start > 1:  # setext: the text is the first line, the underline the next
            return line.strip()
        return re.sub(r"\s+#+\s*$", "", line.strip().lstrip("#")).strip()

    def _section(self, blocks: list[_Block], ref: SectionRef) -> _Span:
        headings = [i for i, b in enumerate(blocks) if b.kind == "heading"]
        if ref.heading is None:
            end = headings[0] if headings else len(blocks)
            return _Span(0, end, 0, "le début du document")

        wanted = _normalise(ref.heading)
        matches = [i for i in headings if _normalise(self._heading_text(blocks[i])) == wanted]
        if len(matches) < ref.occurrence:
            available = ", ".join(f"« {self._heading_text(blocks[i])} »" for i in headings) or "aucun titre"
            raise Refused(f"titre « {ref.heading} » introuvable (occurrence {ref.occurrence}). Titres : {available}.")
        heading = matches[ref.occurrence - 1]
        later = [i for i in headings if i > heading]
        return _Span(heading + 1, later[0] if later else len(blocks), blocks[heading].end, f"« {ref.heading} »")

    def _section_end_line(self, blocks: list[_Block], span: _Span) -> int:
        """Line right after the section's last block (the heading's own end if it is empty)."""
        return blocks[span.end - 1].end if span.end > span.start else span.after_heading

    def _kind_in(self, blocks: list[_Block], span: _Span, kind: str) -> list[_Block]:
        return [b for b in blocks[span.start : span.end] if b.kind == kind]

    def _paragraph(self, ref: SectionRef, number: int) -> tuple[_Span, _Block]:
        blocks = self._blocks()
        span = self._section(blocks, ref)
        paragraphs = self._kind_in(blocks, span, "paragraph")
        if number > len(paragraphs):
            raise Refused(f"{span.label} n'a que {len(paragraphs)} paragraphe(s), pas de paragraphe {number}.")
        return span, paragraphs[number - 1]

    def _insert_line(self, span: _Span, blocks: list[_Block], after_paragraph: int | None) -> int:
        """The line after which a new block goes (0 meaning the very top of the file)."""
        if after_paragraph is None:
            return self._section_end_line(blocks, span)
        if after_paragraph == 0:
            return span.after_heading
        paragraphs = self._kind_in(blocks, span, "paragraph")
        if after_paragraph > len(paragraphs):
            raise Refused(
                f"{span.label} n'a que {len(paragraphs)} paragraphe(s), "
                f"impossible d'insérer après le {after_paragraph}."
            )
        return paragraphs[after_paragraph - 1].end

    def _insert_block(self, after_line: int, new_lines: list[str]) -> None:
        """Adds a block after `after_line` (a line count), separated by a blank line from what
        precedes; at the very top of the file it goes first, followed by a blank line."""
        if after_line == 0:
            self.lines[0:0] = [*new_lines, ""] if any(line.strip() for line in self.lines) else new_lines
        else:
            self.lines[after_line:after_line] = ["", *new_lines]

    def _table_block(self, ref: TableRef) -> tuple[_Block, _TableModel]:
        blocks = self._blocks()
        span = self._section(blocks, ref.section)
        tables = self._kind_in(blocks, span, "table")
        if ref.index > len(tables):
            raise Refused(f"{span.label} contient {len(tables)} tableau(x), pas de tableau {ref.index}.")
        block = tables[ref.index - 1]
        return block, _TableModel.parse(self.lines[block.start : block.end])

    def _write_table(self, block: _Block, model: _TableModel) -> None:
        self.lines[block.start : block.end] = model.render()

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
        span, block = self._paragraph(op.section, op.paragraph)
        self.lines[block.start : block.end] = op.text.split("\n")
        return f"Paragraphe {op.paragraph} de {span.label} remplacé."

    def _insert_paragraph(self, op: InsertParagraph) -> str:
        blocks = self._blocks()
        span = self._section(blocks, op.section)
        self._insert_block(self._insert_line(span, blocks, op.after_paragraph), op.text.split("\n"))
        where = "à la fin" if op.after_paragraph is None else f"après le paragraphe {op.after_paragraph}"
        return f"Paragraphe ajouté {where} de {span.label}."

    def _delete_paragraph(self, op: DeleteParagraph) -> str:
        span, block = self._paragraph(op.section, op.paragraph)
        end = block.end
        # Take one adjacent blank line with it so no double gap is left behind.
        if end < len(self.lines) and not self.lines[end].strip():
            end += 1
        elif block.start > 0 and not self.lines[block.start - 1].strip():
            block.start -= 1
        del self.lines[block.start : end]
        return f"Paragraphe {op.paragraph} de {span.label} supprimé."

    def _insert_section(self, op: InsertSection) -> str:
        blocks = self._blocks()
        if op.after is None:
            line, where = blocks[-1].end if blocks else 0, "à la fin du document"
        else:
            span = self._section(blocks, op.after)
            if op.after.heading is None:
                line, where = self._section_end_line(blocks, span), "après le début du document"
            else:
                heading = span.start - 1
                level = blocks[heading].level
                end = next(
                    (
                        i
                        for i in range(heading + 1, len(blocks))
                        if blocks[i].kind == "heading" and blocks[i].level <= level
                    ),
                    len(blocks),
                )
                line, where = blocks[end - 1].end, f"après la section {span.label}"
        new_lines = [f"{'#' * op.level} {op.title}"]
        for text in op.paragraphs:
            new_lines += ["", *text.split("\n")]
        self._insert_block(line, new_lines)
        return f"Section « {op.title} » (niveau {op.level}) ajoutée {where}."

    def _set_cell(self, op: SetCell) -> str:
        block, model = self._table_block(op.table)
        self._check(model, row=op.row, column=op.column)
        model.all_rows[op.row - 1][op.column - 1] = op.text
        self._write_table(block, model)
        return f"Cellule (ligne {op.row}, colonne {op.column}) modifiée."

    def _insert_row(self, op: InsertRow) -> str:
        block, model = self._table_block(op.table)
        after = len(model.all_rows) if op.after_row is None else op.after_row
        if after > len(model.all_rows):
            raise Refused(
                f"le tableau n'a que {len(model.all_rows)} ligne(s), impossible d'insérer après la ligne {after}."
            )
        if after == 0:
            raise Refused(
                "en Markdown la première ligne d'un tableau est son en-tête : insérez après la ligne 1 ou plus bas."
            )
        if len(op.values) > model.width:
            raise Refused(f"{len(op.values)} valeurs pour un tableau de {model.width} colonne(s).")
        model.rows.insert(after - 1, (op.values + [""] * model.width)[: model.width])
        self._write_table(block, model)
        return f"Ligne ajoutée après la ligne {after} du tableau."

    def _delete_row(self, op: DeleteRow) -> str:
        block, model = self._table_block(op.table)
        self._check(model, row=op.row)
        if op.row == 1:
            raise Refused("la ligne 1 est l'en-tête du tableau, elle ne peut pas être supprimée.")
        del model.rows[op.row - 2]
        self._write_table(block, model)
        return f"Ligne {op.row} du tableau supprimée."

    def _insert_column(self, op: InsertColumn) -> str:
        block, model = self._table_block(op.table)
        after = model.width if op.after_column is None else op.after_column
        if after > model.width:
            raise Refused(
                f"le tableau n'a que {model.width} colonne(s), impossible d'insérer après la colonne {after}."
            )
        if len(op.values) > len(model.all_rows):
            raise Refused(f"{len(op.values)} valeurs pour un tableau de {len(model.all_rows)} ligne(s).")
        for index, row in enumerate(model.all_rows):
            row.insert(after, op.values[index] if index < len(op.values) else "")
        model.alignments.insert(after, "")
        self._write_table(block, model)
        return f"Colonne ajoutée après la colonne {after} du tableau."

    def _delete_column(self, op: DeleteColumn) -> str:
        block, model = self._table_block(op.table)
        self._check(model, column=op.column)
        if model.width == 1:
            raise Refused("impossible de supprimer la dernière colonne du tableau.")
        for row in model.all_rows:
            del row[op.column - 1]
        del model.alignments[op.column - 1]
        self._write_table(block, model)
        return f"Colonne {op.column} du tableau supprimée."

    def _insert_table(self, op: InsertTable) -> str:
        blocks = self._blocks()
        span = self._section(blocks, op.section)
        width = len(op.rows[0])
        if any(len(row) != width for row in op.rows):
            raise Refused("toutes les lignes du tableau doivent avoir le même nombre de cellules.")
        table = _TableModel(op.rows[0], [""] * width, op.rows[1:])
        self._insert_block(self._insert_line(span, blocks, op.after_paragraph), table.render())
        return f"Tableau de {len(op.rows)} ligne(s) et {width} colonne(s) ajouté dans {span.label}."

    @staticmethod
    def _check(model: _TableModel, row: int | None = None, column: int | None = None) -> None:
        if row is not None and row > len(model.all_rows):
            raise Refused(f"le tableau n'a que {len(model.all_rows)} ligne(s), pas de ligne {row}.")
        if column is not None and column > model.width:
            raise Refused(f"le tableau n'a que {model.width} colonne(s), pas de colonne {column}.")


def apply_operations(source: bytes, operations: list[Operation]) -> EditResult:
    """Returns the edited Markdown and one summary line per operation. Raises OperationError -
    naming the failing operation - without producing anything if any of them can't be applied."""
    editor = _Editor(source.decode("utf-8"))
    summary: list[str] = []
    for index, operation in enumerate(operations, start=1):
        try:
            summary.append(editor.apply(operation))
        except Refused as refusal:
            raise OperationError(index, str(refusal)) from refusal
    return EditResult(data=editor.text().encode("utf-8"), summary=summary)


def outline(source: bytes) -> str:
    """The document as the editing agent reads it: each section's numbered paragraphs and tables,
    with a note for the blocks it can't edit (lists, code, quotes, HTML)."""
    editor = _Editor(source.decode("utf-8"))
    sections = [OutlineSection(None, 0, 1, [])]
    seen: dict[str, int] = {}
    paragraphs = tables = 0
    for block in editor._blocks():
        lines = editor.lines[block.start : block.end]
        if block.kind == "heading":
            text = editor._heading_text(block)
            key = _normalise(text)
            seen[key] = seen.get(key, 0) + 1
            sections.append(OutlineSection(text, block.level, seen[key], []))
            paragraphs = tables = 0
        elif block.kind == "paragraph":
            paragraphs += 1
            sections[-1].items.append(paragraph_item(paragraphs, " ".join(lines)))
        elif block.kind == "table":
            tables += 1
            model = _TableModel.parse(lines)
            sections[-1].items.append(table_item(tables, model.all_rows))
        elif not sections[-1].items or sections[-1].items[-1] != _OTHER:
            sections[-1].items.append(_OTHER)  # one note per run of such blocks, not one per block
    return render_outline(sections)
