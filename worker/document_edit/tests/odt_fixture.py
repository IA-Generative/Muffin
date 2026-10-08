"""A small but realistic ODT built with odfdo: custom heading/body/table styles, a list, a table
with a styled header row, a footnote and an embedded image - the things an edit must leave alone."""

import base64
import io

from odfdo import Cell, Document, Frame, Header, List, ListItem, Note, Paragraph, Style, Table

# A 1x1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _style(document: Document, name: str, display: str, **properties) -> None:
    style = Style("paragraph", name=name, display_name=display)
    if properties:
        style.set_properties(area="text", **properties)
    document.insert_style(style, automatic=False)


def _heading(level: int, text: str, style: str) -> Header:
    heading = Header(level, text)
    heading.style = style  # Header ignores its `style` constructor argument
    return heading


def _table_cell(text: str, style: str) -> Cell:
    cell = Cell(text)
    for paragraph in cell.get_paragraphs():
        paragraph.style = style
    return cell


def build_odt() -> bytes:
    document = Document("text")
    for name, display in (
        ("Heading_20_1", "Heading 1"),
        ("Heading_20_2", "Heading 2"),
        ("Corps", "Corps"),
        ("Table_20_Heading", "Table Heading"),
        ("Table_20_Contents", "Table Contents"),
    ):
        _style(document, name, display)
    body = document.body
    body.clear()

    body.append(_heading(1, "Procédure d'onboarding", "Heading_20_1"))
    intro = Paragraph("Ce document décrit l'arrivée d'un nouvel agent.", style="Corps")
    intro.append(Note(note_class="footnote", note_id="ftn1", citation="1", body="Version interne."))
    body.append(intro)
    logo = Paragraph("", style="Corps")
    uri = document.add_file(io.BytesIO(PNG))
    logo.append(Frame.image_frame(uri, size=("1cm", "1cm")))
    body.append(logo)
    body.append(Paragraph("Second paragraphe d'introduction.", style="Corps"))

    body.append(_heading(2, "Étapes", "Heading_20_2"))
    steps = List()
    for text in ("Créer le compte", "Remettre le matériel"):
        item = ListItem()
        item.append(Paragraph(text, style="Corps"))
        steps.append(item)
    body.append(steps)
    body.append(Paragraph("Les étapes sont à suivre dans l'ordre.", style="Corps"))

    body.append(_heading(2, "Matériel par profil", "Heading_20_2"))
    table = Table("Materiel", width=3, height=3, style="TableauMateriel")
    for r, row in enumerate(
        (("Profil", "Matériel", "Délai"), ("Développeur", "Laptop, écran", "3"), ("Chef de projet", "Laptop", "2"))
    ):
        for c, text in enumerate(row):
            table.set_cell((c, r), _table_cell(text, "Table_20_Heading" if r == 0 else "Table_20_Contents"))
    body.append(table)
    body.append(Paragraph("Les délais sont en jours ouvrés.", style="Corps"))

    body.append(_heading(2, "Contacts", "Heading_20_2"))
    body.append(Paragraph("RH : rh@example.org", style="Corps"))
    body.append(Paragraph("IT : it@example.org", style="Corps"))

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
