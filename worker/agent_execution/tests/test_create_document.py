import json

import pytest

from app.config import settings
from tests.conftest import initial_state

COLLECTIONS = [
    {"collection_id": "col-rh", "name": "Procédures RH", "description": "Arrivée et départ des agents"},
    {"collection_id": "col-it", "name": "Support informatique", "description": None},
]
MARKDOWN = "# Accueil des nouveaux agents\n\n## Avant l'arrivée\n\n- Préparer le poste de travail.\n"


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def _router(verdict: dict | None = None, document: str = MARKDOWN):
    """Answers the plan with what `verdict` says (a creation, or a plain search), the writer with `document`, and the
    rest of the pipeline like the plain lookup tests do - so a run that falls through to research completes."""

    def router(system_prompt: str) -> str:
        if "You are the planner" in system_prompt:
            verdict_ = verdict or {"create": False}
            if verdict_.get("create"):
                return json.dumps({"mode": "create", **{k: v for k, v in verdict_.items() if k != "create"}})
            return json.dumps({"mode": "search"})
        if "You write a document for the user" in system_prompt:
            return document
        return "Réponse de recherche."

    return router


def _create(**overrides) -> dict:
    verdict = {
        "create": True,
        "markdown": True,
        "collection_id": "col-rh",
        "candidates": [],
        "title": "Accueil des nouveaux agents",
        "instruction": "Une procédure d'accueil des nouveaux agents",
    }
    verdict.update(overrides)
    return verdict


def _run(make_run, query, verdict, *, collections=COLLECTIONS, document=MARKDOWN):
    graph, fake = make_run(
        [{"id": "col-rh", "name": "Procédures RH", "description": "", "tags": [], "document_count": 2}],
        _router(verdict, document),
    )
    fake.editable_collections = collections
    state = initial_state(query)
    return graph.invoke(state, config=_config(state)), fake, state


def _asked(fake, marker: str) -> bool:
    return any(marker in call[0]["content"] for call in fake.llm_calls)


# -- when it is (not) a creation ----------------------------------------------------------------


def test_a_question_without_a_creation_verb_never_touches_the_creation_machinery(make_run):
    result, fake, _ = _run(make_run, "Quelle est la procédure d'arrivée ?", _create())

    assert fake.editable_collections_calls == []
    assert result["answer"] == "Réponse de recherche."
    assert not any("Collections the user may add a document to" in call[1]["content"] for call in fake.llm_calls)


def test_the_model_saying_it_is_not_a_creation_leaves_the_run_to_the_research_pipeline(make_run):
    result, fake, state = _run(make_run, "Comment créer un compte sur l'intranet ?", {"create": False})

    assert fake.editable_collections_calls == [state["run_id"]]
    assert result["answer"] == "Réponse de recherche."
    assert not _asked(fake, "You write a document for the user")
    assert result.get("edit_proposal") is None


def test_an_unusable_reply_from_the_model_falls_back_to_the_research_pipeline(make_run):
    graph, fake = make_run(
        [{"id": "col-rh", "name": "Procédures RH", "description": "", "tags": [], "document_count": 2}],
        lambda system_prompt: (
            "pas du JSON" if "may be asking you to CREATE" in system_prompt else _router()(system_prompt)
        ),
    )
    fake.editable_collections = COLLECTIONS
    state = initial_state("Crée un document d'accueil")

    result = graph.invoke(state, config=_config(state))

    assert result["answer"] == "Réponse de recherche."


def test_the_model_is_only_shown_the_collections_the_backend_listed_and_the_conversation(make_run):
    _, fake, _ = _run(make_run, "Crée un document d'accueil", _create())

    prompt = next(c[1]["content"] for c in fake.llm_calls if "You are the planner" in c[0]["content"])
    assert "id=col-rh | « Procédures RH » - Arrivée et départ des agents" in prompt
    assert "id=col-it | « Support informatique »" in prompt
    assert "Current message: Crée un document d'accueil" in prompt


# -- the proposal -------------------------------------------------------------------------------


def test_a_document_is_written_and_proposed_not_created(make_run):
    result, fake, _ = _run(make_run, "Crée un document d'accueil des nouveaux agents dans Procédures RH", _create())

    assert result["edit_proposal"] == {
        "kind": "create",
        "status": "pending",
        "collection_id": "col-rh",
        "collection_name": "Procédures RH",
        "name": "Accueil des nouveaux agents",
        "content": MARKDOWN.strip(),
    }
    assert "« Accueil des nouveaux agents »" in result["answer"]
    assert "pas encore créé" in result["answer"]
    assert result["citations"] == []
    # The writer was told what to write, and it was not a search: no research happened.
    writer = next(c for c in fake.llm_calls if "You write a document for the user" in c[0]["content"])
    assert "Document to write: Une procédure d'accueil des nouveaux agents" in writer[1]["content"]
    assert fake.searched_collection_ids == []
    assert ("create_proposed", None) in fake.events


def test_the_name_comes_from_the_first_heading_and_is_safe_as_a_file_name(make_run):
    result, _, _ = _run(
        make_run,
        "Rédige une note sur les accès",
        _create(title="Accès"),
        document='# Accès / badges : "règles"\n\nTexte.',
    )

    assert result["edit_proposal"]["name"] == "Accès badges règles"


def test_without_a_heading_the_models_title_is_used(make_run):
    result, _, _ = _run(make_run, "Rédige une note sur les accès", _create(title="Les accès"), document="Texte seul.")

    assert result["edit_proposal"]["name"] == "Les accès"


def test_a_code_fence_around_the_document_is_removed(make_run):
    result, _, _ = _run(make_run, "Crée une note", _create(), document=f"```markdown\n{MARKDOWN}```")

    assert result["edit_proposal"]["content"] == MARKDOWN.strip()


def test_a_document_too_long_is_cut_at_its_last_whole_paragraph(make_run, monkeypatch):
    monkeypatch.setattr(settings, "CREATE_MAX_CHARS", 40)

    result, _, _ = _run(
        make_run,
        "Crée une note",
        _create(),
        document="# Titre\n\nPremier paragraphe.\n\nSecond paragraphe qui dépasse.",
    )

    assert result["edit_proposal"]["content"] == "# Titre\n\nPremier paragraphe."


def test_an_empty_document_is_reported_without_a_proposal(make_run):
    result, _, _ = _run(make_run, "Crée une note", _create(), document="   ")

    assert result["edit_proposal"] is None
    assert "pas réussi à rédiger" in result["answer"]


# -- where it goes, and in which format ---------------------------------------------------------


def test_the_only_collection_is_used_when_none_is_named(make_run):
    result, _, _ = _run(make_run, "Crée une note de service", _create(collection_id=None), collections=COLLECTIONS[:1])

    assert result["edit_proposal"]["collection_id"] == "col-rh"


@pytest.mark.parametrize("verdict", [_create(collection_id="col-999"), _create(collection_id=None)])
def test_an_id_the_user_was_not_offered_is_never_used_and_the_user_is_asked_where(make_run, verdict):
    result, fake, _ = _run(make_run, "Crée une note de service", verdict)

    assert result.get("edit_proposal") is None
    assert "Dans quelle collection" in result["answer"]
    assert "« Procédures RH »" in result["answer"] and "« Support informatique »" in result["answer"]
    assert not _asked(fake, "You write a document for the user")


def test_candidates_are_only_the_collections_it_was_offered(make_run):
    result, _, _ = _run(
        make_run, "Crée une note de service", _create(collection_id=None, candidates=["col-it", "col-999"])
    )

    assert "« Support informatique »" in result["answer"]
    assert "« Procédures RH »" not in result["answer"]


@pytest.mark.parametrize("query", ["Crée un document Word sur l'accueil", "Rédige un tableur Excel des congés"])
def test_only_markdown_can_be_created(make_run, query):
    result, fake, _ = _run(make_run, query, _create(markdown=False))

    assert result.get("edit_proposal") is None
    assert "Markdown" in result["answer"] and ".md" in result["answer"]
    assert not _asked(fake, "You write a document for the user")


def test_a_user_with_no_collection_to_write_in_is_told_so(make_run):
    result, _, _ = _run(make_run, "Crée une note de service", _create(), collections=[])

    assert result.get("edit_proposal") is None
    assert "aucune collection" in result["answer"]


def test_a_request_to_change_a_document_is_left_to_the_edit_path(make_run):
    graph, fake = make_run(
        [{"id": "col-rh", "name": "Procédures RH", "description": "", "tags": [], "document_count": 2}],
        _router(_create()),
    )
    fake.editable_documents = [
        {
            "document_id": "doc-1",
            "name": "procedure.odt",
            "collection_id": "col-rh",
            "collection_name": "RH",
            "summary": None,
        }
    ]
    fake.editable_collections = COLLECTIONS
    fake.edit_states = [
        {"status": "ready", "job_kind": "edit", "edited": True, "operations_summary": "- Ajouté.", "error": None}
    ]

    def router(system_prompt: str) -> str:
        if "You are the planner" in system_prompt:
            return json.dumps({"mode": "edit", "document_id": "doc-1", "candidates": [], "instruction": "Ajoute 15"})
        return _router(_create())(system_prompt)

    fake.llm_router = router
    state = initial_state("Rédige le numéro d'urgence dans procedure.odt et ajoute-le")

    result = graph.invoke(state, config=_config(state))

    assert fake.edit_creates and result["edit_proposal"]["document_id"] == "doc-1"
    # A message that looks like both is shown both lists; the plan decides, and an edit never writes a document.
    assert not any("You write a document for the user" in call[0]["content"] for call in fake.llm_calls)


# -- the agent knows what it can do -------------------------------------------------------------


def test_the_agent_tells_what_it_can_edit_and_create_when_asked_what_it_can_do(make_run):
    def router(system_prompt: str) -> str:
        if "You are the planner" in system_prompt:
            return json.dumps({"mode": "direct", "answer": "Je suis Muffin."})
        return "Je suis Muffin."

    graph, fake = make_run([], router)
    state = initial_state("Peux-tu modifier ou créer un fichier ?")

    graph.invoke(state, config=_config(state))

    capabilities = next(c[0]["content"] for c in fake.llm_calls if "You are the planner" in c[0]["content"])
    assert "Modify an existing living document" in capabilities
    assert "Markdown (.md) only, never Word" in capabilities
    assert "always reviews and validates first" in capabilities
