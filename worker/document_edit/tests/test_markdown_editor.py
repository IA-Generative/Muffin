import pytest

from app.edit_types import OperationError
from app.markdown_editor import apply_operations
from app.operations import OperationList

DOCUMENT = """\
# Procédure d'onboarding

Ce document décrit l'arrivée d'un nouvel agent.
Il tient sur deux lignes.

Second paragraphe d'introduction.

## Étapes

1. Créer le compte
2. Remettre le matériel

Les étapes sont à suivre dans l'ordre.

```bash
# ceci n'est pas un titre
echo "ok"
```

## Matériel par profil

| Profil         | Matériel      |  Délai |
|:---------------|:-------------:|-------:|
| Développeur    | Laptop, écran |      3 |
| Chef de projet | Laptop        |      2 |

> Les délais sont en jours ouvrés.

<!-- note interne -->

## Contacts

RH : rh@example.org

IT : it@example.org
"""

CONTACTS = {"heading": "Contacts"}
MATERIEL = {"heading": "Matériel par profil"}
TABLE = {"section": MATERIEL}


def _ops(*operations: dict):
    return OperationList.validate_python(list(operations))


def _apply(*operations: dict, source: str = DOCUMENT) -> str:
    return apply_operations(source.encode(), _ops(*operations)).data.decode()


def _changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    """Lines only in `before` and lines only in `after` - everything else is untouched."""
    old, new = before.split("\n"), after.split("\n")
    return [line for line in old if line not in new], [line for line in new if line not in old]


# -- paragraphs -------------------------------------------------------------------------------


def test_replace_paragraph_touches_only_its_own_lines():
    result = _apply({"op": "replace_paragraph", "section": CONTACTS, "paragraph": 2, "text": "IT : help@example.org"})

    assert _changed_lines(DOCUMENT, result) == (["IT : it@example.org"], ["IT : help@example.org"])
    assert len(result.split("\n")) == len(DOCUMENT.split("\n"))


def test_a_two_line_paragraph_is_one_paragraph():
    result = _apply(
        {"op": "replace_paragraph", "section": {"heading": "Procédure d'onboarding"}, "paragraph": 1, "text": "Neuf."}
    )
    assert result.startswith("# Procédure d'onboarding\n\nNeuf.\n\nSecond paragraphe")


def test_a_hash_inside_a_code_fence_is_not_a_heading_and_code_is_not_a_paragraph():
    result = _apply({"op": "insert_paragraph", "section": {"heading": "Étapes"}, "text": "Ajout"})

    assert "# ceci n'est pas un titre" in result
    # The fence belongs to the section and stays intact; the new paragraph goes after it.
    assert '```bash\n# ceci n\'est pas un titre\necho "ok"\n```\n\nAjout\n\n## Matériel' in result


def test_insert_paragraph_at_the_end_after_n_and_right_under_the_heading():
    result = _apply(
        {"op": "insert_paragraph", "section": CONTACTS, "text": "Fin"},
        {"op": "insert_paragraph", "section": CONTACTS, "after_paragraph": 1, "text": "Milieu"},
        {"op": "insert_paragraph", "section": CONTACTS, "after_paragraph": 0, "text": "Début"},
    )

    assert result.endswith("## Contacts\n\nDébut\n\nRH : rh@example.org\n\nMilieu\n\nIT : it@example.org\n\nFin\n")


def test_insert_paragraph_in_the_intro_before_the_first_heading():
    source = "Texte libre.\n\n# Titre\n\nCorps.\n"
    result = _apply({"op": "insert_paragraph", "section": {}, "after_paragraph": 0, "text": "Avant"}, source=source)
    assert result == "Avant\n\nTexte libre.\n\n# Titre\n\nCorps.\n"


def test_delete_paragraph_leaves_no_double_gap():
    result = _apply({"op": "delete_paragraph", "section": CONTACTS, "paragraph": 1})
    assert result.endswith("## Contacts\n\nIT : it@example.org\n")

    last = _apply({"op": "delete_paragraph", "section": CONTACTS, "paragraph": 2})
    assert last.endswith("## Contacts\n\nRH : rh@example.org\n")


# -- sections ---------------------------------------------------------------------------------


def test_insert_section_at_the_end_and_after_a_section():
    result = _apply(
        {"op": "insert_section", "level": 2, "title": "Annexes", "paragraphs": ["A", "B"]},
        {"op": "insert_section", "after": {"heading": "Étapes"}, "level": 2, "title": "Prérequis", "paragraphs": ["P"]},
    )

    headings = [line for line in result.split("\n") if line.startswith("## ")]
    assert headings == ["## Étapes", "## Prérequis", "## Matériel par profil", "## Contacts", "## Annexes"]
    assert result.endswith("## Annexes\n\nA\n\nB\n")
    assert "Les étapes sont à suivre dans l'ordre.\n\n```bash" in result
    assert 'echo "ok"\n```\n\n## Prérequis\n\nP\n\n## Matériel' in result


def test_insert_section_after_a_parent_goes_after_its_subsections():
    source = "# A\n\n## A1\n\nx\n\n# B\n\ny\n"
    result = _apply({"op": "insert_section", "after": {"heading": "A"}, "level": 1, "title": "A bis"}, source=source)
    assert result == "# A\n\n## A1\n\nx\n\n# A bis\n\n# B\n\ny\n"


def test_setext_headings_are_recognised():
    source = "Titre\n=====\n\nCorps.\n"
    result = _apply({"op": "insert_paragraph", "section": {"heading": "Titre"}, "text": "Suite"}, source=source)
    assert result == "Titre\n=====\n\nCorps.\n\nSuite\n"


def test_heading_lookup_ignores_case_and_spacing_and_honours_occurrence():
    result = _apply(
        {"op": "insert_section", "level": 2, "title": "Contacts"},
        {"op": "insert_paragraph", "section": {"heading": "  CONTACTS ", "occurrence": 2}, "text": "Dans le second"},
    )
    assert result.endswith("## Contacts\n\nDans le second\n")


# -- tables -----------------------------------------------------------------------------------


def _table_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("|")]


def test_set_cell_rerenders_only_that_table_and_keeps_alignments():
    result = _apply({"op": "set_cell", "table": TABLE, "row": 2, "column": 2, "text": "Laptop, écran 27 pouces"})

    assert _table_lines(result) == [
        "| Profil         |         Matériel        | Délai |",
        "| :------------- | :---------------------: | ----: |",
        "| Développeur    | Laptop, écran 27 pouces |     3 |",
        "| Chef de projet |          Laptop         |     2 |",
    ]
    before_lines, after_lines = _changed_lines(DOCUMENT, result)
    assert not [line for line in before_lines if not line.startswith("|")]
    assert not [line for line in after_lines if not line.startswith("|")]


def test_insert_row_at_the_bottom_and_in_the_middle():
    result = _apply(
        {"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]},
        {"op": "insert_row", "table": TABLE, "after_row": 1, "values": ["Designer", "Tablette"]},
    )

    rows = [[c.strip() for c in line.strip("|").split("|")] for line in _table_lines(result)]
    assert [row[0] for row in rows] == ["Profil", ":---", "Designer", "Développeur", "Chef de projet", "QA"][:1] + [
        row[0] for row in rows[1:]
    ]
    assert [row[0] for row in rows if not row[0].startswith((":", "-"))] == [
        "Profil",
        "Designer",
        "Développeur",
        "Chef de projet",
        "QA",
    ]
    assert rows[3 - 1][1:] == ["Tablette", ""]


def test_header_row_is_protected():
    with pytest.raises(OperationError, match="en-tête"):
        _apply({"op": "insert_row", "table": TABLE, "after_row": 0, "values": ["x"]})
    with pytest.raises(OperationError, match="en-tête"):
        _apply({"op": "delete_row", "table": TABLE, "row": 1})


def test_delete_row_and_column():
    result = _apply(
        {"op": "delete_row", "table": TABLE, "row": 2},
        {"op": "delete_column", "table": TABLE, "column": 2},
    )

    assert _table_lines(result) == [
        "| Profil         | Délai |",
        "| :------------- | ----: |",
        "| Chef de projet |     2 |",
    ]


def test_insert_column_right_middle_and_left_keeps_the_other_alignments():
    result = _apply(
        {"op": "insert_column", "table": TABLE, "values": ["Budget", "100", "200"]},
        {"op": "insert_column", "table": TABLE, "after_column": 0, "values": ["N°", "1", "2"]},
    )

    lines = _table_lines(result)
    assert [c.strip() for c in lines[0].strip("|").split("|")] == ["N°", "Profil", "Matériel", "Délai", "Budget"]
    rules = [c.strip() for c in lines[1].strip("|").split("|")]
    assert rules[1].startswith(":") and not rules[1].endswith(":")  # Profil: left
    assert rules[2].startswith(":") and rules[2].endswith(":")  # Matériel: centre
    assert rules[3].endswith(":") and not rules[3].startswith(":")  # Délai: right


def test_a_pipe_and_a_newline_in_a_cell_are_escaped():
    result = _apply({"op": "set_cell", "table": TABLE, "row": 2, "column": 1, "text": "a|b\nc"})
    assert "| a\\|b<br>c" in result
    # ...and survive a round trip through another edit.
    again = apply_operations(
        result.encode(), _ops({"op": "set_cell", "table": TABLE, "row": 3, "column": 3, "text": "9"})
    )
    assert "| a\\|b<br>c" in again.data.decode()


def test_insert_table_after_a_paragraph_and_at_the_end():
    result = _apply(
        {
            "op": "insert_table",
            "section": CONTACTS,
            "after_paragraph": 1,
            "rows": [["Service", "Email"], ["RH", "rh@x.org"]],
        }
    )

    assert (
        "RH : rh@example.org\n\n| Service | Email    |\n| ------- | -------- |\n| RH      | rh@x.org |\n\nIT : it"
        in result
    )


def test_everything_the_operations_do_not_name_survives_byte_for_byte():
    result = _apply(
        {"op": "replace_paragraph", "section": CONTACTS, "paragraph": 1, "text": "RH : nouveau@example.org"},
        {"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]},
    )

    for kept in (
        "# Procédure d'onboarding\n\nCe document décrit l'arrivée d'un nouvel agent.\nIl tient sur deux lignes.\n",
        "1. Créer le compte\n2. Remettre le matériel\n",
        '```bash\n# ceci n\'est pas un titre\necho "ok"\n```\n',
        "> Les délais sont en jours ouvrés.\n\n<!-- note interne -->\n",
        "IT : it@example.org\n",
    ):
        assert kept in result


def test_crlf_files_keep_their_line_endings_and_a_missing_final_newline_stays_missing():
    crlf = DOCUMENT.replace("\n", "\r\n")
    result = _apply({"op": "insert_paragraph", "section": CONTACTS, "text": "Fin"}, source=crlf)
    assert result.endswith("IT : it@example.org\r\n\r\nFin\r\n")
    assert "\n" not in result.replace("\r\n", "")

    no_newline = "# T\n\nCorps."
    assert _apply({"op": "insert_paragraph", "section": {"heading": "T"}, "text": "Suite"}, source=no_newline) == (
        "# T\n\nCorps.\n\nSuite"
    )


def test_an_edited_file_can_be_edited_again():
    first = _apply({"op": "insert_row", "table": TABLE, "values": ["QA", "Laptop", "4"]})
    second = apply_operations(first.encode(), _ops({"op": "delete_row", "table": TABLE, "row": 4})).data.decode()

    # Same cells and alignments as the original (only the padding differs after a re-render).
    def compact(text: str) -> list[str]:
        return [line.replace(" ", "").replace("-", "") for line in _table_lines(text)]

    assert compact(second) == compact(DOCUMENT)


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
            {"op": "insert_row", "table": TABLE, "after_row": 1, "values": list("abcd")},
            "4 valeurs pour un tableau de 3",
        ),
        ({"op": "insert_row", "table": TABLE, "after_row": 9}, "impossible d'insérer après la ligne 9"),
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


def test_the_last_column_cannot_be_deleted():
    with pytest.raises(OperationError, match="dernière colonne"):
        _apply(
            {"op": "delete_column", "table": TABLE, "column": 1},
            {"op": "delete_column", "table": TABLE, "column": 1},
            {"op": "delete_column", "table": TABLE, "column": 1},
        )
