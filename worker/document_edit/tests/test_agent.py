import json

import pytest

from app.agent import SYSTEM_PROMPT, EditFailedError, run_edit_agent
from tests.odt_fixture import build_odt
from tests.test_markdown_editor import DOCUMENT as MARKDOWN

CONTACTS = {"heading": "Contacts"}
GOOD_REPLY = json.dumps(
    {
        "operations": [
            {"op": "insert_paragraph", "section": CONTACTS, "text": "Urgences : 0 800 000 000"},
            {
                "op": "insert_row",
                "table": {"section": {"heading": "Matériel par profil"}},
                "values": ["QA", "Laptop", "4"],
            },
        ],
        "message": "J'ai ajouté le numéro d'urgence et le profil QA.",
    }
)


class ScriptedLlm:
    """Stands in for the model: returns the scripted replies in order and remembers every call."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


def _run(llm, *, fmt="odt", prompt="Ajoute un numéro d'urgence", **options):
    source = build_odt() if fmt == "odt" else MARKDOWN.encode()
    return source, run_edit_agent(source, fmt, prompt, llm, **options)


def test_a_valid_reply_is_applied_and_summarised():
    llm = ScriptedLlm(GOOD_REPLY)

    source, outcome = _run(llm)

    assert outcome.edited is True
    assert outcome.attempts == 1
    assert outcome.data != source
    assert outcome.summary == [
        "Paragraphe ajouté à la fin de « Contacts ».",
        "Ligne ajoutée après la ligne 3 du tableau.",
    ]
    assert outcome.message == "J'ai ajouté le numéro d'urgence et le profil QA."
    assert len(llm.calls) == 1


def test_the_model_is_given_the_outline_the_vocabulary_and_the_request():
    llm = ScriptedLlm(GOOD_REPLY)

    _run(llm, prompt="Ajoute un numéro d'urgence")

    system, user = llm.calls[0]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    assert "replace_paragraph" in SYSTEM_PROMPT and "insert_table" in SYSTEM_PROMPT
    assert "## « Contacts » (niveau 2, occurrence 1)" in user["content"]
    assert "¶2 IT : it@example.org" in user["content"]
    assert "Tableau 1 (3 ligne(s) × 3 colonne(s))" in user["content"]
    assert "ODT (LibreOffice)" in user["content"]
    assert user["content"].endswith("Demande de l'utilisateur :\nAjoute un numéro d'urgence")


def test_a_json_wrapped_in_a_code_fence_or_a_sentence_is_accepted():
    fenced = ScriptedLlm("```json\n" + GOOD_REPLY + "\n```")
    chatty = ScriptedLlm("Voici ma proposition :\n" + GOOD_REPLY + "\nBonne journée !")

    assert _run(fenced)[1].edited is True
    assert _run(chatty)[1].edited is True


def test_an_invalid_json_is_retried_with_the_reason_and_the_refused_answer():
    llm = ScriptedLlm("je vais modifier le document", GOOD_REPLY)

    _, outcome = _run(llm)

    assert outcome.attempts == 2
    assert outcome.edited is True
    retry = llm.calls[1]
    assert retry[-2] == {"role": "assistant", "content": "je vais modifier le document"}
    assert "n'a pas pu être appliquée" in retry[-1]["content"]
    assert "JSON" in retry[-1]["content"]


def test_an_unknown_operation_is_retried_and_the_error_names_the_field():
    bad = json.dumps({"operations": [{"op": "format_hard_drive"}]})
    llm = ScriptedLlm(bad, GOOD_REPLY)

    _, outcome = _run(llm)

    assert outcome.attempts == 2
    assert "les opérations sont invalides" in llm.calls[1][-1]["content"]


def test_an_operation_aimed_at_nothing_is_retried_with_the_available_headings():
    wrong = json.dumps({"operations": [{"op": "insert_paragraph", "section": {"heading": "Coordonnées"}, "text": "x"}]})
    llm = ScriptedLlm(wrong, GOOD_REPLY)

    _, outcome = _run(llm)

    assert outcome.attempts == 2
    feedback = llm.calls[1][-1]["content"]
    assert "Opération 1" in feedback
    assert "« Coordonnées » introuvable" in feedback
    assert "« Contacts »" in feedback


def test_an_edit_that_would_destroy_an_image_or_a_footnote_is_refused_and_retried():
    destroying = json.dumps(
        {
            "operations": [
                {
                    "op": "replace_paragraph",
                    "section": {"heading": "Procédure d'onboarding"},
                    "paragraph": 1,
                    "text": "Réécrit",
                }
            ]
        }
    )
    llm = ScriptedLlm(destroying, GOOD_REPLY)

    _run(llm)

    assert "note de bas de page" in llm.calls[1][-1]["content"]


def test_the_agent_gives_up_after_the_allowed_attempts_and_says_why():
    llm = ScriptedLlm("non", "toujours pas", "encore non")

    with pytest.raises(EditFailedError) as error:
        _run(llm, max_attempts=3)

    assert len(llm.calls) == 3
    assert "3 tentative(s)" in error.value.message
    assert "Reformulez" in error.value.message
    # The reason addressed to the model is not what the user is shown.
    assert "ta réponse" not in error.value.message


def test_a_request_the_model_declines_changes_nothing_and_carries_its_explanation():
    declined = json.dumps({"operations": [], "message": "Je ne peux pas modifier une liste."})

    source, outcome = _run(ScriptedLlm(declined))

    assert outcome.edited is False
    assert outcome.data == source
    assert outcome.summary == []
    assert outcome.message == "Je ne peux pas modifier une liste."


def test_pending_images_are_numbered_and_keep_their_position():
    reply = json.dumps(
        {
            "operations": [{"op": "insert_paragraph", "section": CONTACTS, "text": "Plan d'accès :"}],
            "pending_images": [
                {"description": "Plan d'accès au bâtiment", "section": CONTACTS, "after_paragraph": 3},
                {"description": "Logo"},
            ],
        }
    )

    _, outcome = _run(ScriptedLlm(reply))

    assert [(i.id, i.description, i.after_paragraph) for i in outcome.pending_images] == [
        ("img-1", "Plan d'accès au bâtiment", 3),
        ("img-2", "Logo", None),
    ]
    assert outcome.pending_images[0].section.heading == "Contacts"
    assert outcome.pending_images[1].section is None


def test_a_pending_image_without_a_description_is_retried():
    bad = json.dumps({"operations": [], "pending_images": [{"section": CONTACTS}]})
    llm = ScriptedLlm(bad, GOOD_REPLY)

    _, outcome = _run(llm)

    assert outcome.attempts == 2
    assert "description" in llm.calls[1][-1]["content"]


def test_a_markdown_document_is_edited_the_same_way():
    llm = ScriptedLlm(GOOD_REPLY)

    source, outcome = _run(llm, fmt="md")

    assert "Markdown" in llm.calls[0][1]["content"]
    assert outcome.data.decode().endswith("IT : it@example.org\n\nUrgences : 0 800 000 000\n")
    assert "| QA" in outcome.data.decode()


def test_a_document_too_large_for_the_model_fails_before_any_call():
    llm = ScriptedLlm()

    with pytest.raises(EditFailedError, match="trop volumineux"):
        _run(llm, max_outline_chars=100)

    assert llm.calls == []
