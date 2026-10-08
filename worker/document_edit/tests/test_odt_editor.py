import io
import shutil
import subprocess
import zipfile

import pytest
from odfdo import Cell, Document, Header, Table
from pydantic import ValidationError

from app.odt_editor import OperationError, apply_operations
from app.operations import OperationList
from tests.odt_fixture import PNG, build_odt


def _ops(*operations: dict):
    return OperationList.validate_python(list(operations))


def _apply(*operations: dict):
    return apply_operations(build_odt(), _ops(*operations))


def _doc(data: bytes) -> Document:
    return Document(io.BytesIO(data))


def _outline(data: bytes) -> list[tuple[str, str, str | None]]:
    """(tag, text, style) of every body-level element, in order."""
    return [(c.tag, c.text_recursive.strip(), c.style) for c in _doc(data).body.children]


def _texts(data: bytes) -> list[str]:
    return [text for _, text, _ in _outline(data)]


def _table(data: bytes):
    return next(c for c in _doc(data).body.children if c.tag == "table:table")


def _rows(data: bytes) -> list[list[str]]:
    table = _table(data)
    return [table.get_row_values(i) for i in range(len(table.get_rows()))]


INTRO = {"heading": "Procédure d'onboarding"}
STEPS = {"heading": "Étapes"}
MATERIEL = {"heading": "Matériel par profil"}
CONTACTS = {"heading": "Contacts"}
TABLE = {"section": MATERIEL}


# -- paragraphs -------------------------------------------------------------------------------


def test_replace_paragraph_changes_only_that_paragraph_and_keeps_its_style():
    before = _outline(build_odt())
    result = _apply({"op": "replace_paragraph", "section": CONTACTS, "paragraph": 2, "text": "IT : help@example.org"})

    after = _outline(result.data)
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert changed == [(("text:p", "IT : it@example.org", "Corps"), ("text:p", "IT : help@example.org", "Corps"))]
    assert result.summary == ["Paragraphe 2 de « Contacts » remplacé."]


def test_replace_paragraph_in_the_intro_counts_the_image_paragraph():
    # The paragraph holding the logo is the 2nd of the section (the footnote one is the 1st).
    result = _apply({"op": "replace_paragraph", "section": INTRO, "paragraph": 3, "text": "Nouveau texte"})
    assert "Nouveau texte" in _texts(result.data)
    assert "Second paragraphe d'introduction." not in _texts(result.data)


@pytest.mark.parametrize(("paragraph", "carries"), [(1, "une note de bas de page"), (2, "une image")])
def test_replacing_a_paragraph_that_carries_a_footnote_or_an_image_is_refused(paragraph, carries):
    with pytest.raises(OperationError, match=carries):
        _apply({"op": "replace_paragraph", "section": INTRO, "paragraph": paragraph, "text": "Réécrit"})


@pytest.mark.parametrize(("paragraph", "carries"), [(1, "une note de bas de page"), (2, "une image")])
def test_deleting_a_paragraph_that_carries_a_footnote_or_an_image_is_refused_too(paragraph, carries):
    # Otherwise "insert a new paragraph, delete the old one" would drop them just the same.
    with pytest.raises(OperationError, match=f"contient {carries}.*supprimer"):
        _apply({"op": "delete_paragraph", "section": INTRO, "paragraph": paragraph})


def test_insert_paragraph_at_the_end_after_n_and_right_under_the_heading_uses_the_neighbour_style():
    result = _apply(
        {"op": "insert_paragraph", "section": CONTACTS, "text": "Fin"},
        {"op": "insert_paragraph", "section": CONTACTS, "after_paragraph": 1, "text": "Milieu"},
        {"op": "insert_paragraph", "section": CONTACTS, "after_paragraph": 0, "text": "Début"},
    )

    section = _outline(result.data)[-6:]
    assert section == [
        ("text:h", "Contacts", "Heading_20_2"),
        ("text:p", "Début", "Corps"),
        ("text:p", "RH : rh@example.org", "Corps"),
        ("text:p", "Milieu", "Corps"),
        ("text:p", "IT : it@example.org", "Corps"),
        ("text:p", "Fin", "Corps"),
    ]


def test_delete_paragraph():
    result = _apply({"op": "delete_paragraph", "section": CONTACTS, "paragraph": 1})
    assert _texts(result.data)[-2:] == ["Contacts", "IT : it@example.org"]


def test_a_new_paragraph_in_a_section_without_paragraphs_gets_the_documents_main_style():
    result = _apply(
        {"op": "insert_section", "level": 2, "title": "Vide"},
        {"op": "insert_paragraph", "section": {"heading": "Vide"}, "text": "Premier"},
    )
    assert _outline(result.data)[-1] == ("text:p", "Premier", "Corps")


# -- sections ---------------------------------------------------------------------------------


def test_insert_section_at_the_end_reuses_heading_and_body_styles():
    result = _apply({"op": "insert_section", "level": 2, "title": "Annexes", "paragraphs": ["A", "B"]})

    assert _outline(result.data)[-3:] == [
        ("text:h", "Annexes", "Heading_20_2"),
        ("text:p", "A", "Corps"),
        ("text:p", "B", "Corps"),
    ]
    assert result.summary == ["Section « Annexes » (niveau 2) ajoutée à la fin du document."]


def test_insert_section_after_a_section_goes_after_its_subsections():
    result = _apply(
        # The level-1 title owns every section below it: "after" it means at the very end...
        {"op": "insert_section", "after": INTRO, "level": 2, "title": "Contexte", "paragraphs": ["x"]},
        # ...and a level-3 section goes right after its parent, a level-2 sibling after the block.
        {"op": "insert_section", "after": {"heading": "Contexte"}, "level": 3, "title": "Détail"},
        {"op": "insert_section", "after": STEPS, "level": 2, "title": "Prérequis"},
    )
    headings = [t for tag, t, _ in _outline(result.data) if tag == "text:h"]
    assert headings == [
        "Procédure d'onboarding",
        "Étapes",
        "Prérequis",
        "Matériel par profil",
        "Contacts",
        "Contexte",
        "Détail",
    ]


def test_insert_section_copies_the_style_of_an_existing_heading_of_that_level():
    document = _doc(build_odt())
    for heading in document.body.get_headers():
        if int(heading.level) == 2:
            heading.style = "Table_20_Heading"  # anything recognisable, distinct from Heading_20_2
    buffer = io.BytesIO()
    document.save(buffer)

    result = apply_operations(buffer.getvalue(), _ops({"op": "insert_section", "level": 2, "title": "Annexes"}))

    assert _outline(result.data)[-1] == ("text:h", "Annexes", "Table_20_Heading")


def test_a_level_without_a_styled_heading_falls_back_to_the_named_style_the_document_defines():
    # No level-3 heading exists, but the document defines "Heading 3" in its styles.
    result = _apply({"op": "insert_section", "level": 3, "title": "Détail"})
    heading = _doc(result.data).body.children[-1]
    assert isinstance(heading, Header)
    assert int(heading.level) == 3
    assert heading.style == "Heading_20_3"


def test_heading_lookup_ignores_case_and_spacing_and_honours_occurrence():
    result = _apply(
        {"op": "insert_section", "level": 2, "title": "Contacts"},
        {"op": "insert_paragraph", "section": {"heading": "  CONTACTS ", "occurrence": 2}, "text": "Dans le second"},
    )
    texts = _texts(result.data)
    assert texts[-2:] == ["Contacts", "Dans le second"]


# -- tables -----------------------------------------------------------------------------------


def test_set_cell_keeps_the_cell_paragraph_style():
    result = _apply({"op": "set_cell", "table": TABLE, "row": 2, "column": 2, "text": "Laptop, écran 27 pouces"})

    table = _table(result.data)
    assert _rows(result.data)[1] == ["Développeur", "Laptop, écran 27 pouces", "3"]
    assert table.get_cell((1, 1)).get_paragraphs()[0].style == "Table_20_Contents"
    assert table.get_cell((1, 0)).get_paragraphs()[0].style == "Table_20_Heading"


def test_insert_row_at_the_bottom_in_the_middle_and_on_top_is_formatted_like_a_data_row():
    result = _apply(
        {"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]},
        {"op": "insert_row", "table": TABLE, "after_row": 1, "values": ["Designer", "Tablette"]},
        {"op": "insert_row", "table": TABLE, "after_row": 0, "values": ["Profil", "Matériel", "Délai"]},
    )

    assert _rows(result.data) == [
        ["Profil", "Matériel", "Délai"],
        ["Profil", "Matériel", "Délai"],
        ["Designer", "Tablette", ""],
        ["Développeur", "Laptop, écran", "3"],
        ["Chef de projet", "Laptop", "2"],
        ["QA", "Laptop", "4"],
    ]
    table = _table(result.data)
    # Inserted under the header: a data-row style, not a header style.
    assert table.get_cell((0, 2)).get_paragraphs()[0].style == "Table_20_Contents"
    # The header row is still the header.
    assert table.get_cell((0, 1)).get_paragraphs()[0].style == "Table_20_Heading"


def test_delete_row_and_refuse_to_delete_the_last_one():
    result = _apply({"op": "delete_row", "table": TABLE, "row": 2})
    assert _rows(result.data) == [["Profil", "Matériel", "Délai"], ["Chef de projet", "Laptop", "2"]]

    with pytest.raises(OperationError, match="dernière ligne"):
        _apply(
            {"op": "delete_row", "table": TABLE, "row": 1},
            {"op": "delete_row", "table": TABLE, "row": 1},
            {"op": "delete_row", "table": TABLE, "row": 1},
        )


def test_insert_column_on_the_right_in_the_middle_and_on_the_left():
    result = _apply(
        {"op": "insert_column", "table": TABLE, "values": ["Budget", "100", "200"]},
        {"op": "insert_column", "table": TABLE, "after_column": 1, "values": ["Site"]},
        {"op": "insert_column", "table": TABLE, "after_column": 0, "values": ["N°", "1", "2"]},
    )

    assert _rows(result.data) == [
        ["N°", "Profil", "Site", "Matériel", "Délai", "Budget"],
        ["1", "Développeur", "", "Laptop, écran", "3", "100"],
        ["2", "Chef de projet", "", "Laptop", "2", "200"],
    ]
    table = _table(result.data)
    # New cells are formatted like the column they were added next to.
    for column in (0, 2, 5):
        assert table.get_cell((column, 0)).get_paragraphs()[0].style == "Table_20_Heading"
        assert table.get_cell((column, 1)).get_paragraphs()[0].style == "Table_20_Contents"


def test_delete_column_and_refuse_to_delete_the_last_one():
    result = _apply({"op": "delete_column", "table": TABLE, "column": 2})
    assert _rows(result.data)[0] == ["Profil", "Délai"]

    with pytest.raises(OperationError, match="dernière colonne"):
        _apply(
            {"op": "delete_column", "table": TABLE, "column": 1},
            {"op": "delete_column", "table": TABLE, "column": 1},
            {"op": "delete_column", "table": TABLE, "column": 1},
        )


def test_insert_table_borrows_the_existing_tables_styles():
    result = _apply(
        {
            "op": "insert_table",
            "section": CONTACTS,
            "rows": [["Service", "Email"], ["RH", "rh@example.org"], ["IT", "it@example.org"]],
        }
    )

    tables = [c for c in _doc(result.data).body.children if c.tag == "table:table"]
    assert len(tables) == 2
    new = tables[1]
    assert new.style == "TableauMateriel"
    assert new.name != tables[0].name
    assert [new.get_row_values(i) for i in range(3)] == [
        ["Service", "Email"],
        ["RH", "rh@example.org"],
        ["IT", "it@example.org"],
    ]
    assert new.get_cell((0, 0)).get_paragraphs()[0].style == "Table_20_Heading"
    assert new.get_cell((1, 2)).get_paragraphs()[0].style == "Table_20_Contents"
    # Added at the end of the section, right after its last paragraph.
    texts = _texts(result.data)
    assert texts.index("IT : it@example.org") < len(texts) - 1


def test_insert_table_after_a_given_paragraph():
    result = _apply({"op": "insert_table", "section": CONTACTS, "after_paragraph": 1, "rows": [["a", "b"]]})
    assert [tag for tag, _, _ in _outline(result.data)][-4:] == ["text:h", "text:p", "table:table", "text:p"]


def test_a_numeric_cell_given_a_number_stays_numeric_and_a_text_makes_it_a_string():
    document = Document("text")
    document.body.clear()
    table = Table("T", width=1, height=2)
    table.set_cell((0, 0), Cell("Total"))
    table.set_cell((0, 1), Cell(3))
    document.body.append(Header(1, "Chiffres"))
    document.body.append(table)
    buffer = io.BytesIO()
    document.save(buffer)
    numbers = {"heading": "Chiffres"}

    as_number = apply_operations(
        buffer.getvalue(), _ops({"op": "set_cell", "table": {"section": numbers}, "row": 2, "column": 1, "text": "5,5"})
    )
    as_text = apply_operations(
        buffer.getvalue(), _ops({"op": "set_cell", "table": {"section": numbers}, "row": 2, "column": 1, "text": "n/a"})
    )

    number_cell = _table(as_number.data).get_cell((0, 1))
    assert number_cell.get_attribute("office:value-type") == "float"
    assert number_cell.value == 5.5
    assert _table(as_text.data).get_cell((0, 1)).get_attribute("office:value-type") == "string"


# -- what an edit must not touch ------------------------------------------------------------


def _pictures(data: bytes) -> dict[str, bytes]:
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {name: archive.read(name) for name in archive.namelist() if name.startswith("Pictures/")}


def test_everything_the_operations_do_not_name_survives():
    source = build_odt()
    result = apply_operations(
        source,
        _ops(
            {"op": "replace_paragraph", "section": CONTACTS, "paragraph": 1, "text": "RH : nouveau@example.org"},
            {"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]},
            {"op": "insert_section", "level": 2, "title": "Annexes", "paragraphs": ["A"]},
        ),
    )

    before, after = _doc(source), _doc(result.data)
    # Footnote and image frame are still there, the embedded picture byte for byte.
    assert len(after.body.get_notes()) == len(before.body.get_notes()) == 1
    assert len(after.body.get_frames()) == len(before.body.get_frames()) == 1
    assert _pictures(result.data) == _pictures(source)
    assert PNG in _pictures(result.data).values()

    # Every element no operation targeted is byte-identical: the footnote paragraph, the image
    # paragraph, the list, the other sections' paragraphs and headings.
    def serialised(document: Document) -> dict[tuple[str, str], str]:
        return {(c.tag, c.text_recursive.strip()): c.serialize() for c in document.body.children}

    kept = serialised(before)
    now = serialised(after)
    targeted = {("text:p", "RH : rh@example.org"), ("table:table", _table(source).text_recursive.strip())}
    assert len(kept) - len(targeted) >= 10
    for key, xml in kept.items():
        if key not in targeted:
            assert now[key] == xml, key
    # The styles the document declares are still declared.
    assert after.get_style("paragraph", "Corps") is not None
    assert after.get_style("paragraph", "Table_20_Heading") is not None


def test_an_edited_file_can_be_edited_again():
    first = _apply({"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]})
    second = apply_operations(first.data, _ops({"op": "delete_row", "table": TABLE, "row": 4}))
    assert _rows(second.data) == _rows(build_odt())


# -- failures -----------------------------------------------------------------------------------


def test_a_missing_heading_names_the_available_ones():
    with pytest.raises(OperationError) as error:
        _apply({"op": "delete_paragraph", "section": {"heading": "Inexistant"}, "paragraph": 1})

    assert error.value.index == 1
    assert "« Inexistant » introuvable" in error.value.message
    assert "« Contacts »" in error.value.message


def test_a_failing_operation_reports_its_index_and_nothing_is_produced():
    with pytest.raises(OperationError) as error:
        _apply(
            {"op": "insert_paragraph", "section": CONTACTS, "text": "OK"},
            {"op": "replace_paragraph", "section": CONTACTS, "paragraph": 9, "text": "x"},
        )
    assert error.value.index == 2
    # The first operation had already added a third paragraph in memory when the second failed.
    assert "n'a que 3 paragraphe(s)" in error.value.message


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"op": "set_cell", "table": TABLE, "row": 9, "column": 1, "text": "x"}, "pas de ligne 9"),
        ({"op": "set_cell", "table": TABLE, "row": 1, "column": 9, "text": "x"}, "pas de colonne 9"),
        (
            {"op": "set_cell", "table": {"section": MATERIEL, "index": 2}, "row": 1, "column": 1, "text": "x"},
            "pas de tableau 2",
        ),
        (
            {"op": "insert_row", "table": TABLE, "values": ["a", "b", "c", "d"]},
            "4 valeurs pour un tableau de 3 colonne",
        ),
        ({"op": "insert_row", "table": TABLE, "after_row": 9}, "impossible d'insérer après la ligne 9"),
        (
            {"op": "insert_column", "table": TABLE, "values": ["a", "b", "c", "d"]},
            "4 valeurs pour un tableau de 3 ligne",
        ),
        ({"op": "insert_table", "section": CONTACTS, "rows": [["a", "b"], ["c"]]}, "même nombre de cellules"),
        (
            {"op": "insert_paragraph", "section": CONTACTS, "after_paragraph": 9, "text": "x"},
            "impossible d'insérer après le 9",
        ),
    ],
)
def test_invalid_operations_are_refused_with_a_readable_message(operation, message):
    with pytest.raises(OperationError, match=message):
        _apply(operation)


# -- the operation vocabulary -------------------------------------------------------------------


def test_operations_are_parsed_from_plain_dicts_with_their_defaults():
    (operation,) = _ops({"op": "insert_row", "table": {"section": {"heading": "X"}}})
    assert operation.after_row is None
    assert operation.table.index == 1
    assert operation.table.section.occurrence == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "format_hard_drive"},
        {"op": "replace_paragraph", "section": {"heading": "X"}, "paragraph": 0, "text": "x"},
        {"op": "insert_section", "level": 7, "title": "x"},
        {"op": "insert_table", "section": {}, "rows": []},
    ],
)
def test_unknown_or_malformed_operations_are_rejected(bad):
    with pytest.raises(ValidationError):
        _ops(bad)


# -- the real thing: does LibreOffice still open it? ------------------------------------------


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed here")
def test_libreoffice_opens_an_edited_file(tmp_path):
    result = _apply(
        {"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]},
        {"op": "insert_column", "table": TABLE, "values": ["Budget", "1", "2", "3"]},
        {"op": "insert_section", "level": 2, "title": "Annexes", "paragraphs": ["A"]},
    )
    source = tmp_path / "edited.odt"
    source.write_bytes(result.data)

    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(source)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert (tmp_path / "edited.pdf").read_bytes().startswith(b"%PDF")
