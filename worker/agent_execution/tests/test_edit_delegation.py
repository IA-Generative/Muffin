import json

import pytest

from app.backend_client import EditRequestRefused, _refusal
from app.config import settings
from tests.conftest import initial_state

DOC_ID = "doc-1"
DOCS = [
    {
        "document_id": DOC_ID,
        "name": "procedure.odt",
        "collection_id": "col-1",
        "collection_name": "Procédures RH",
        "summary": "Les étapes d'arrivée d'un nouvel agent.",
    },
    {
        "document_id": "doc-2",
        "name": "glossaire.md",
        "collection_id": "col-1",
        "collection_name": "Procédures RH",
        "summary": None,
    },
]
PROPOSAL = {"collection_id": "col-1", "document_id": DOC_ID, "document_name": "procedure.odt"}


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def _draft(status="pending", **overrides) -> dict:
    draft = {
        "status": status,
        "job_kind": "edit",
        "edited": False,
        "operations_summary": "",
        "error": None,
        "preview": None,
        "pending_images": [],
    }
    draft.update(overrides)
    return draft


def _router(edit_verdict: dict | None = None):
    """Answers the detect_edit prompt with `edit_verdict`, and the rest of the pipeline like the
    plain lookup tests do - so a run that falls through to research still completes."""

    def router(system_prompt: str) -> str:
        if "may be asking to CHANGE" in system_prompt:
            return json.dumps(edit_verdict or {"edit": False})
        if "Analyze the user" in system_prompt:
            return json.dumps({"intent": "lookup", "ambiguous": False, "complexity": "simple"})
        if "select the ones relevant" in system_prompt.lower():
            return '["col-1"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "Réponse de recherche."

    return router


def _vdbs() -> list[dict]:
    return [{"id": "col-1", "name": "Procédures RH", "description": "", "tags": [], "document_count": 2}]


def _edit(**overrides) -> dict:
    verdict = {"edit": True, "document_id": DOC_ID, "candidates": [], "instruction": "Ajoute le numéro 15"}
    verdict.update(overrides)
    return verdict


@pytest.fixture(autouse=True)
def _bounded_wait(monkeypatch):
    # Safety net: a test that forgets to give the draft an ending would otherwise spin on a
    # "pending" draft for the real default wait.
    monkeypatch.setattr(settings, "EDIT_WAIT_SECONDS", 2)


def _run(make_run, query: str, verdict: dict | None, *, docs=DOCS, states=None):
    graph, fake = make_run(_vdbs(), _router(verdict))
    fake.editable_documents = docs
    fake.edit_states = states or [_draft("ready", edited=True, operations_summary="- Paragraphe ajouté.")]
    state = initial_state(query)
    return graph.invoke(state, config=_config(state)), fake, state


# -- when it is (not) an edit -------------------------------------------------------------------


def test_a_question_without_an_edit_verb_never_touches_the_edit_machinery(make_run):
    result, fake, _ = _run(make_run, "Quelle est la procédure d'arrivée ?", _edit())

    assert fake.editable_calls == []
    assert result["answer"] == "Réponse de recherche."
    assert not any("may be asking to CHANGE" in call[0]["content"] for call in fake.llm_calls)


def test_a_message_that_looks_like_an_edit_but_has_nothing_editable_goes_on_as_a_question(make_run):
    result, fake, state = _run(make_run, "Ajoute le numéro 15 dans la procédure", _edit(), docs=[])

    assert fake.editable_calls == [state["run_id"]]
    assert fake.edit_creates == []
    assert result["answer"] == "Réponse de recherche."  # the research pipeline answered
    assert not any("may be asking to CHANGE" in call[0]["content"] for call in fake.llm_calls)


def test_the_model_saying_it_is_not_an_edit_leaves_the_run_to_the_research_pipeline(make_run):
    result, fake, _ = _run(make_run, "Peux-tu changer de sujet ? Parle-moi de la procédure", {"edit": False})

    assert fake.edit_creates == []
    assert result["answer"] == "Réponse de recherche."


@pytest.mark.parametrize("verdict", [_edit(document_id="doc-999"), _edit(document_id=None), {"edit": True}])
def test_an_id_the_user_was_not_offered_is_never_acted_on(make_run, verdict):
    result, fake, _ = _run(make_run, "Ajoute le numéro 15 dans la procédure", verdict)

    assert fake.edit_creates == []
    assert result["answer"] == "Réponse de recherche."


def test_an_unusable_reply_from_the_model_falls_back_to_the_research_pipeline(make_run):
    def router(system_prompt: str) -> str:
        if "may be asking to CHANGE" in system_prompt:
            return "pas du JSON"
        return _router()(system_prompt)

    graph, fake = make_run(_vdbs(), router)
    fake.editable_documents = DOCS
    state = initial_state("Ajoute le numéro 15 dans la procédure")

    result = graph.invoke(state, config=_config(state))

    assert fake.edit_creates == []
    assert result["answer"] == "Réponse de recherche."


def test_the_model_is_only_shown_documents_the_backend_listed_and_the_conversation(make_run):
    _, fake, _ = _run(make_run, "Ajoute le numéro 15", _edit())

    prompt = next(c for c in fake.llm_calls if "may be asking to CHANGE" in c[0]["content"])[1]["content"]
    assert f"id={DOC_ID} | « procedure.odt » (collection « Procédures RH ») - Les étapes d'arrivée" in prompt
    assert "id=doc-2 | « glossaire.md »" in prompt
    assert prompt.endswith("Current message: Ajoute le numéro 15")


# -- delegating ---------------------------------------------------------------------------------


def test_an_edit_is_delegated_to_the_backend_with_the_run_identity_and_waits_for_the_result(make_run):
    states = [
        _draft("pending"),
        _draft("pending"),
        _draft(
            "ready",
            edited=True,
            preview="pdf",
            operations_summary=(
                "- Paragraphe ajouté à la fin de « Contacts ».\n- Ligne ajoutée après la ligne 3 du tableau."
            ),
        ),
    ]

    result, fake, state = _run(make_run, "Ajoute le numéro 15 dans la procédure", _edit(), states=states)

    # What it asked for - the instruction the model restated, for the document it picked.
    assert fake.edit_creates == [(state["run_id"], DOC_ID, "Ajoute le numéro 15")]
    assert fake.edit_polls == 2  # it waited through two "pending" states, then stopped
    assert result["edit_proposal"] == PROPOSAL
    assert result["answer"].startswith("J'ai préparé une modification de « procedure.odt » :")
    assert "- Paragraphe ajouté à la fin de « Contacts »." in result["answer"]
    assert "- Ligne ajoutée après la ligne 3 du tableau." in result["answer"]
    assert "Elle n'est pas encore enregistrée" in result["answer"]
    assert result["citations"] == []
    # It never went looking in the knowledge bases: this was not a question.
    assert result["completed_task_ids"] == []


def test_each_wait_checks_for_a_cancellation_and_stops_cleanly(make_run):
    graph, fake = make_run(_vdbs(), _router(_edit()))
    fake.editable_documents = DOCS
    fake.edit_states = [_draft("pending")]
    polls = {"count": 0}
    original = fake.get_edit_request

    def cancelling(run_id, document_id):
        polls["count"] += 1
        fake.cancel_requested = True
        return original(run_id, document_id)

    fake.get_edit_request = cancelling
    state = initial_state("Ajoute le numéro 15 dans la procédure")

    result = graph.invoke(state, config=_config(state))

    assert result.get("cancelled") is True
    assert result["answer"] is None
    assert polls["count"] == 1  # noticed on the very next round: no second question to the backend


def test_a_draft_the_editing_agent_could_not_make_is_reported_with_the_card_kept(make_run):
    states = [_draft("pending"), _draft("failed", error="Aucun modèle de chat n'est configuré.")]

    result, _, _ = _run(make_run, "Ajoute le numéro 15 dans la procédure", _edit(), states=states)

    assert (
        result["answer"]
        == "La modification de « procedure.odt » n'a pas abouti : Aucun modèle de chat n'est configuré."
    )
    assert result["edit_proposal"] == PROPOSAL


def test_an_agent_that_declines_has_its_explanation_relayed(make_run):
    states = [
        _draft("pending"),
        _draft("ready", edited=False, operations_summary="La liste des étapes n'est pas modifiable."),
    ]

    result, _, _ = _run(make_run, "Ajoute une étape à la liste", _edit(instruction="Ajoute une étape"), states=states)

    assert result["answer"] == "Je n'ai pas modifié « procedure.odt » : La liste des étapes n'est pas modifiable."
    assert result["edit_proposal"] == PROPOSAL


def test_a_wait_that_runs_out_says_the_proposal_will_appear(make_run, monkeypatch):
    monkeypatch.setattr(settings, "EDIT_WAIT_SECONDS", 0)

    result, fake, _ = _run(make_run, "Ajoute le numéro 15 dans la procédure", _edit(), states=[_draft("pending")])

    assert fake.edit_polls == 0
    assert "travaille encore" in result["answer"]
    assert result["edit_proposal"] == PROPOSAL


def test_a_draft_that_disappears_while_waiting_is_reported(make_run):
    graph, fake = make_run(_vdbs(), _router(_edit()))
    fake.editable_documents = DOCS
    fake.edit_states = [_draft("pending")]
    fake.edit_gone = EditRequestRefused(404, None, "Ce document est introuvable.")
    state = initial_state("Ajoute le numéro 15 dans la procédure")

    result = graph.invoke(state, config=_config(state))

    assert result["answer"] == "Ce document est introuvable."
    assert result["edit_proposal"] is None


# -- when the backend says no -------------------------------------------------------------------


def test_a_proposal_already_waiting_is_pointed_to_rather_than_hidden(make_run):
    graph, fake = make_run(_vdbs(), _router(_edit()))
    fake.editable_documents = DOCS
    fake.edit_refusal = EditRequestRefused(
        409, "draft_exists", "Ce document a déjà un brouillon : validez-le ou refusez-le d'abord."
    )
    state = initial_state("Ajoute le numéro 15 dans la procédure")

    result = graph.invoke(state, config=_config(state))

    assert result["answer"] == "Ce document a déjà un brouillon : validez-le ou refusez-le d'abord."
    assert result["edit_proposal"] == PROPOSAL  # the card to go and deal with it


@pytest.mark.parametrize(
    "refusal",
    [
        EditRequestRefused(403, None, "Vous n'avez pas le droit de modifier ce document."),
        EditRequestRefused(409, "document_locked", "Ce document est en cours de modification par Marie L."),
    ],
)
def test_other_refusals_are_told_to_the_user_without_a_card(make_run, refusal):
    graph, fake = make_run(_vdbs(), _router(_edit()))
    fake.editable_documents = DOCS
    fake.edit_refusal = refusal
    state = initial_state("Ajoute le numéro 15 dans la procédure")

    result = graph.invoke(state, config=_config(state))

    assert result["answer"] == refusal.message
    assert result["edit_proposal"] is None
    assert fake.edit_polls == 0


def test_several_possible_documents_make_the_agent_ask_instead_of_guessing(make_run):
    verdict = {"edit": True, "document_id": None, "candidates": [DOC_ID, "doc-2"], "instruction": "Ajoute le numéro 15"}

    result, fake, _ = _run(make_run, "Ajoute le numéro 15 dans le document", verdict)

    assert fake.edit_creates == []
    assert result["answer"].startswith("Plusieurs documents modifiables pourraient correspondre")
    assert "- « procedure.odt » (collection « Procédures RH »)" in result["answer"]
    assert "- « glossaire.md » (collection « Procédures RH »)" in result["answer"]
    assert result["edit_proposal"] is None


def test_candidates_are_only_the_documents_it_was_offered(make_run):
    verdict = {"edit": True, "document_id": None, "candidates": [DOC_ID, "doc-999"], "instruction": "x"}

    result, fake, _ = _run(make_run, "Ajoute le numéro 15 dans le document", verdict)

    # Only one real candidate: not ambiguous, and not an id to act on - an ordinary question.
    assert fake.edit_creates == []
    assert result["answer"] == "Réponse de recherche."


# -- the backend client's reading of a refusal --------------------------------------------------


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _Error(Exception):
    def __init__(self, response):
        self.response = response


@pytest.mark.parametrize(
    ("status", "body", "code", "message"),
    [
        (
            409,
            {"detail": {"code": "draft_exists", "message": "Déjà un brouillon."}},
            "draft_exists",
            "Déjà un brouillon.",
        ),
        (
            409,
            {"detail": {"code": "document_locked", "locked_by_display": "Marie L.", "held_by_me": False}},
            "document_locked",
            "Ce document est en cours de modification par Marie L.",
        ),
        (
            403,
            {"detail": "Only the collection's owner or an administrator can edit it"},
            None,
            "Vous n'avez pas le droit",
        ),
        (404, {"detail": "Document not found"}, None, "introuvable"),
        (500, None, None, "(500)"),
    ],
)
def test_the_backends_refusals_become_messages_for_the_user(status, body, code, message):
    refusal = _refusal(_Error(_Response(status, body)))

    assert refusal.status_code == status and refusal.code == code
    assert message in refusal.message
