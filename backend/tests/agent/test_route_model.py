"""Auto mode: when the person picks no model, a short call rates the request and the model whose score covers it
writes the run. A model picked by hand is used as it is, and nothing that goes wrong in the choice fails the run."""

import json

from app.agent.graph.nodes.route_model import choose, classify
from tests.agent.conftest import initial_state
from tests.agent.test_graph import VDBS, _config, router

SMALL = {"model": "small", "score": 20, "description": "Quick lookups and chit-chat.", "vision": False}
MEDIUM = {"model": "medium", "score": 55, "description": "Summaries and comparisons.", "vision": True}
LARGE = {"model": "large", "score": 90, "description": "Hard reasoning, long documents.", "vision": False}
OFFER = {"candidates": [SMALL, MEDIUM, LARGE], "classifier_model": None}
RATING = "You rate how demanding a request is"


def rating(level, **extra):
    return json.dumps({"level": level, "complexity": "moderate", "intent": "summary", "reason": "r", **extra})


async def run(make_run, query="Résume ce contrat", *, offer=OFFER, rated=None, requested_model=None, **state_kwargs):
    inner = router({"mode": "search", "collections": ["col-hr"]})

    def llm_router(system_prompt: str) -> str:
        if RATING in system_prompt:
            if isinstance(rated, Exception):
                raise rated
            return rated if rated is not None else rating(50)
        return inner(system_prompt)

    graph, fake = make_run(VDBS, llm_router)
    fake.auto_offer = offer
    fake.models_used = []
    for name in ("llm_chat", "llm_chat_with_usage"):
        original = getattr(fake, name)

        async def spy(model, messages, *args, _original=original, **kwargs):
            fake.models_used.append((model, messages[0]["content"]))
            return await _original(model, messages, *args, **kwargs)

        setattr(fake, name, spy)
    state = initial_state(query, **state_kwargs)
    if requested_model:
        state |= {"requested_model": requested_model, "chat_model": requested_model}
    result = await graph.ainvoke(state, config=_config(state))
    return result, fake


def models_by_step(fake) -> dict[str, str]:
    steps = {"classifier": RATING, "plan": "You are the planner"}
    return {step: model for model, prompt in fake.models_used for step, marker in steps.items() if marker in prompt}


# --- the choice, in code ---


def test_the_cheapest_model_that_covers_the_level_is_chosen():
    classification = {"level": 40, "preferred_model": None}

    assert choose([SMALL, MEDIUM, LARGE], classification, needs_vision=False) == MEDIUM


def test_when_no_model_covers_the_level_the_best_one_is_taken():
    assert choose([SMALL, MEDIUM], {"level": 95, "preferred_model": None}, needs_vision=False) == MEDIUM


def test_a_preferred_model_wins_over_a_cheaper_one_when_it_covers_the_level():
    classification = {"level": 30, "preferred_model": "large"}

    assert choose([SMALL, MEDIUM, LARGE], classification, needs_vision=False) == LARGE


def test_a_preferred_model_that_is_too_weak_is_ignored():
    classification = {"level": 60, "preferred_model": "small"}

    assert choose([SMALL, MEDIUM, LARGE], classification, needs_vision=False) == LARGE


def test_with_images_the_models_that_read_them_come_first():
    classification = {"level": 10, "preferred_model": None}

    assert choose([SMALL, MEDIUM, LARGE], classification, needs_vision=True) == MEDIUM


def test_the_classification_is_bounded_and_keeps_known_words_only():
    raw = {"level": 400, "complexity": "gigantic", "intent": "poetry", "preferred_model": "ghost", "reason": 3}

    assert classify(raw, [SMALL]) == {
        "level": 100,
        "complexity": "moderate",
        "intent": "other",
        "preferred_model": None,
        "reason": "3",
    }
    assert classify({"level": "high"}, [SMALL]) is None
    assert classify("nonsense", [SMALL]) is None


# --- in the graph ---


async def test_an_easy_request_goes_to_a_small_model_and_a_hard_one_to_a_large_model(make_run):
    _, easy = await run(make_run, "Bonjour", rated=rating(5))
    _, hard = await run(make_run, "Analyse ces 40 contrats", rated=rating(85))

    assert models_by_step(easy)["plan"] == "small"
    assert models_by_step(hard)["plan"] == "large"
    assert {model for model, _ in hard.models_used if model != models_by_step(hard)["classifier"]} == {"large"}


async def test_the_classifier_is_the_cheapest_model_unless_an_administrator_chose_one(make_run):
    _, default = await run(make_run, rated=rating(50))
    _, chosen = await run(make_run, offer={**OFFER, "classifier_model": "medium"}, rated=rating(50))

    assert models_by_step(default)["classifier"] == "small"
    assert models_by_step(chosen)["classifier"] == "medium"


async def test_the_choice_is_recorded_on_the_run_and_in_its_events(make_run):
    _, fake = await run(make_run, rated=rating(50, intent="analysis", reason="Needs a comparison"))

    [(_, routing)] = [event for event in fake.event_data if event[0] == "model_routed"]
    assert routing["model"] == "medium" and routing["level"] == 50 and routing["intent"] == "analysis"
    assert routing["reason"] == "Needs a comparison"


async def test_a_model_picked_by_hand_is_used_as_it_is_without_a_classifier_call(make_run):
    _, fake = await run(make_run, requested_model="hand-picked")

    assert {model for model, _ in fake.models_used} == {"hand-picked"}
    assert not any(RATING in prompt for _, prompt in fake.models_used)


async def test_a_classifier_that_fails_leaves_the_default_model(make_run):
    result, fake = await run(make_run, rated=RuntimeError("hub down"))

    assert result["answer"] and models_by_step(fake)["plan"] == "test-model"
    assert "model_routed" not in [kind for kind, _ in fake.event_data]


async def test_a_classifier_that_answers_nonsense_leaves_the_default_model(make_run):
    _, fake = await run(make_run, rated="I think it is hard.")

    assert models_by_step(fake)["plan"] == "test-model"


async def test_without_rated_models_nothing_changes(make_run):
    _, fake = await run(make_run, offer={"candidates": [], "classifier_model": None})

    assert models_by_step(fake)["plan"] == "test-model"
    assert not any(RATING in prompt for _, prompt in fake.models_used)


async def test_a_single_model_is_chosen_without_asking_a_classifier(make_run):
    _, fake = await run(make_run, offer={"candidates": [LARGE], "classifier_model": None})

    assert models_by_step(fake)["plan"] == "large"
    assert not any(RATING in prompt for _, prompt in fake.models_used)
