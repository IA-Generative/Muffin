import io

from odfdo import Document, Header, Paragraph

from app.editing import outline
from tests.odt_fixture import build_odt
from tests.test_markdown_editor import DOCUMENT as MARKDOWN


def test_the_odt_outline_numbers_paragraphs_and_tables_per_section_and_flags_what_is_protected():
    text = outline(build_odt(), "odt")

    assert text.startswith("## « Procédure d'onboarding » (niveau 1, occurrence 1)\n")
    assert "  ¶1 Ce document décrit l'arrivée d'un nouvel agent.  [contient une note de bas de page" in text
    assert "[contient une image : ne peut être ni remplacé ni supprimé]" in text
    assert "  ¶3 Second paragraphe d'introduction." in text
    # The footnote's own text and the image path are not shown as if they were the paragraph's words.
    assert "Version interne" not in text
    assert "Pictures/" not in text
    note = "[liste de 2 élément(s), non modifiable : aucune opération ne peut la viser]"
    assert f"## « Étapes » (niveau 2, occurrence 1)\n  {note}\n  ¶1 Les étapes" in text
    assert (
        "  Tableau 1 (3 ligne(s) × 3 colonne(s)) :\n"
        "    L1: Profil | Matériel | Délai\n"
        "    L2: Développeur | Laptop, écran | 3\n"
        "    L3: Chef de projet | Laptop | 2\n"
    ) in text
    assert "## « Contacts » (niveau 2, occurrence 1)\n  ¶1 RH : rh@example.org\n  ¶2 IT : it@example.org" in text


def test_the_markdown_outline_groups_blocks_it_cannot_edit():
    text = outline(MARKDOWN.encode(), "md")

    assert "  ¶1 Ce document décrit l'arrivée d'un nouvel agent. Il tient sur deux lignes." in text
    note = "[bloc non modifiable (liste, code, citation ou HTML) : aucune opération ne peut le viser]"
    assert f"## « Étapes » (niveau 2, occurrence 1)\n  {note}\n  ¶1 Les étapes" in text
    # The list, the fence, the quote and the HTML comment are noted, not quoted - one note per run
    # of such blocks: the list; the fence; the quote followed by the comment.
    assert "echo" not in text and "Les délais sont" not in text
    assert text.count("[bloc non modifiable") == 3
    assert "    L2: Développeur | Laptop, écran | 3" in text


def test_repeated_headings_get_their_occurrence_number():
    document = Document("text")
    document.body.clear()
    for title in ("Annexe", "Annexe"):
        document.body.append(Header(1, title))
        document.body.append(Paragraph(f"Texte de {title}"))
    buffer = io.BytesIO()
    document.save(buffer)

    text = outline(buffer.getvalue(), "odt")

    assert "(niveau 1, occurrence 1)" in text and "(niveau 1, occurrence 2)" in text


def test_content_before_the_first_heading_is_listed_and_an_empty_document_says_so():
    assert outline(b"Texte libre.\n\n# Titre\n\nCorps.\n", "md").startswith(
        "## Début du document (avant le premier titre)\n  ¶1 Texte libre."
    )
    assert outline(b"", "md") == "(document vide)"


def test_a_long_paragraph_and_a_long_table_are_clipped():
    long_text = "mot " * 1000
    rows = "\n".join(f"| ligne {i} | x |" for i in range(60))
    source = f"# T\n\n{long_text}\n\n| a | b |\n|---|---|\n{rows}\n".encode()

    text = outline(source, "md")

    assert "…" in text.split("\n")[1]
    assert len(text.split("\n")[1]) < 1600
    assert "… (21 ligne(s) de plus)" in text
