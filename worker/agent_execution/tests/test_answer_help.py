import json

from app.graph.nodes import answer_help
from tests.conftest import initial_state

GUIDE_ANSWER = "Ouvrez les paramètres de la collection, section « Partages », puis « Inviter »."


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def _router(intent: str = "help", *, ambiguous: bool = False):
    """`intent` is what the plan decides: the help of the application, or a search over the documents."""

    def router(system_prompt: str) -> str:
        if "You are the planner" in system_prompt:
            if intent == "help":
                return json.dumps({"mode": "help", "standalone_query": "Comment je partage une collection ?"})
            return json.dumps({"mode": "search"})
        if "help of Muffin" in system_prompt:
            return GUIDE_ANSWER
        return "Réponse de recherche."

    return router


VDBS = [{"id": "col-1", "name": "Procédures RH", "description": "", "tags": [], "document_count": 2}]


def _run(make_run, query, **kwargs):
    graph, fake = make_run(VDBS, _router(**kwargs))
    state = initial_state(query)
    return graph.invoke(state, config=_config(state)), fake


def test_a_question_about_using_the_application_is_answered_from_the_guide_without_searching(make_run):
    result, fake = _run(make_run, "Comment je partage une collection ?")

    assert result["answer"] == GUIDE_ANSWER
    assert result["citations"] == []
    # Nothing was searched: no routing to collections, no research, no grounding pass.
    assert fake.searched_collection_ids == [] and fake.collection_search_calls == []
    assert not any("select the ones relevant" in call[0]["content"].lower() for call in fake.llm_calls)
    assert [call[0]["content"].split(",")[0] for call in fake.llm_calls][-1].startswith("You are the help of Muffin")


def test_the_model_gets_the_guide_and_the_standalone_question(make_run):
    _, fake = _run(make_run, "Comment je partage une collection ?")

    system, user = next(c for c in fake.llm_calls if "help of Muffin" in c[0]["content"])
    assert "USER GUIDE" in system["content"]
    assert "Partages" in system["content"] and "Never invent a button" in system["content"]
    assert user["content"] == "Question: Comment je partage une collection ?"


def test_a_help_question_is_never_held_back_by_a_clarification(make_run):
    result, fake = _run(make_run, "Comment je partage une collection ?", ambiguous=True)

    assert result["answer"] == GUIDE_ANSWER
    assert "Plusieurs" not in result["answer"]


def test_the_guide_version_is_recorded_when_it_comes_from_the_backend(make_run):
    graph, fake = make_run(VDBS, _router())
    fake.active_prompts["app_help"] = {"id": "ver-help-1", "content": "You are the help of Muffin. Custom guide."}
    state = initial_state("Où importer un ZIP ?")

    result = graph.invoke(state, config=_config(state))

    assert "ver-help-1" in result["prompt_usages"]
    system, _ = next(c for c in fake.llm_calls if "help of Muffin" in c[0]["content"])
    assert system["content"] == "You are the help of Muffin. Custom guide."


def test_a_question_about_documents_is_still_a_search(make_run):
    result, fake = _run(make_run, "Quelle est la procédure d'arrivée ?", intent="lookup")

    assert result["answer"] == "Réponse de recherche."
    assert not any("help of Muffin" in call[0]["content"] for call in fake.llm_calls)


def test_without_a_chat_model_the_help_says_it_cannot_answer(make_run):
    graph, fake = make_run(VDBS, _router())
    state = {**initial_state("Comment je partage une collection ?"), "query_analysis": {"intent": "help"}}
    state["chat_model"] = None

    out = answer_help.answer_help(state)

    assert "ne peux pas répondre" in out["answer"] and out["citations"] == []
    assert fake.llm_calls == []


def test_the_guide_only_describes_what_the_application_really_has():
    """The labels the guide quotes are the ones on screen: a rename in the interface is a reason to
    revisit it, and these are the ones people ask about most."""
    guide = answer_help._SYSTEM_PROMPT
    for label in ("« Nouveau chat »", "« Partages »", "« Inviter »", "« + Nouvelle collection »", "« Révisions »"):
        assert label in guide
    assert "Markdown" in guide and "jamais du Word" in guide
