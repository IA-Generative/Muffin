"""The images of a message (#512) in the agent: the plan is told of them and never answers without them, only the model
that writes the answer reads them - the one chosen when it can, otherwise a model of the hub that can, said in the run's
events - and an answer to an image needs no excerpt."""

import base64

from tests.agent.conftest import initial_state
from tests.agent.test_graph import VDBS, _config, planner_calls, router

PNG = b"\x89PNG\r\n\x1a\n" + b"not a real image, the fake model does not look"
IMAGE = {"id": "img-1", "content_type": "image/png", "current": True}
NO_QUERY = {"mode": "search", "queries": []}


async def run(make_run, query="Que dit ce tableau ?", plan=None, *, vision=("vision-1",), images=(IMAGE,), **kwargs):
    graph, fake = make_run(VDBS, router(plan or NO_QUERY, answer="Le tableau montre trois colonnes."))
    fake.vision_models = list(vision)
    fake.run_images = {image["id"]: (PNG, image["content_type"]) for image in images}
    state = initial_state(query, images=list(images), **kwargs)
    return await graph.ainvoke(state, config=_config(state)), fake


def answer_call(fake) -> list:
    """The call that wrote the answer: the last one."""
    return fake.llm_calls[-1]


def kinds(fake) -> list[str]:
    return [kind for kind, _ in fake.event_data]


# --- the plan ---


async def test_the_plan_is_told_how_many_images_there_are_and_never_gets_them(make_run):
    _, fake = await run(make_run)

    [call] = planner_calls(fake)
    assert "The user attached 1 image(s) to this message." in call[1]["content"]
    assert "You cannot see them" in call[0]["content"]
    assert all(isinstance(message["content"], str) for message in call)  # no image goes to the plan


async def test_images_of_the_previous_message_are_said_to_be_such(make_run):
    _, fake = await run(make_run, "Et la deuxième colonne ?", images=({**IMAGE, "current": False},))

    [call] = planner_calls(fake)
    assert "to the previous message" in call[1]["content"] and "follow-up" in call[1]["content"]


async def test_a_run_without_images_is_what_it_was_and_asks_for_no_model_nor_image(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    state = initial_state("Combien ?")

    await graph.ainvoke(state, config=_config(state))

    assert "attached" not in planner_calls(fake)[0][1]["content"] and "Images:" not in fake.llm_calls[-1][0]["content"]
    assert getattr(fake, "image_requests", []) == [] and "image_reading_started" not in kinds(fake)


async def test_a_plan_that_would_answer_or_ask_without_the_image_goes_on_to_the_model_that_reads_it(make_run):
    for plan in (
        {"mode": "direct", "answer": "Je ne vois pas d'image."},
        {"mode": "clarify", "questions": [{"question": "Quelle image ?", "header": "Image", "options": []}]},
    ):
        result, fake = await run(make_run, plan=plan)

        assert result["answer"] == "Le tableau montre trois colonnes."
        assert len(fake.llm_calls) == 2  # the plan and the answer: nothing was lost, nothing added


# --- the answer ---


async def test_the_answer_is_written_from_the_image_alone_when_nothing_was_searched(make_run):
    result, fake = await run(make_run)

    assert result["answer"] == "Le tableau montre trois colonnes."
    assert "couldn't find" not in result["answer"] and fake.searched_collection_ids == []
    user = answer_call(fake)[1]["content"]
    assert isinstance(user, list) and user[0]["type"] == "text" and "answer from the attached image" in user[0]["text"]
    [part] = user[1:]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"] == f"data:image/png;base64,{base64.b64encode(PNG).decode()}"
    assert "Images:" in answer_call(fake)[0]["content"]  # the rule that says what an image needs and does not


async def test_an_image_and_a_search_make_one_answer_from_both(make_run):
    plan = {"mode": "search", "queries": [{"query": "tableau des congés", "tool": "search"}]}

    result, fake = await run(make_run, plan=plan)

    user = answer_call(fake)[1]["content"]
    assert fake.searched_collection_ids and "evidence about 'tableau des congés'" in user[0]["text"]
    assert user[1]["type"] == "image_url" and result["answer"] == "Le tableau montre trois colonnes."


async def test_only_the_call_that_writes_the_answer_carries_the_images(make_run):
    _, fake = await run(make_run)

    carrying = [call for call in fake.llm_calls if any(isinstance(m["content"], list) for m in call)]
    assert carrying == [answer_call(fake)] and fake.image_requests == ["img-1"]


async def test_the_images_do_not_make_the_check_of_the_claims_run(make_run):
    result, _ = await run(make_run, plan={"mode": "search", "queries": [], "complexity": "complex"})

    assert result["needs_grounding"] is False  # what the model says of an image is not in the evidence it would read


# --- the model that reads them ---


async def test_a_model_that_cannot_read_images_is_replaced_by_one_that_can_and_the_run_says_so(make_run):
    _, fake = await run(make_run, vision=("vision-1", "vision-2"))

    assert ("answer_model_switched", {"from": "test-model", "to": "vision-1", "reason": "images"}) in fake.event_data
    assert ("image_reading_started", {"count": 1}) in fake.event_data


async def test_a_model_that_reads_images_is_kept_and_nothing_is_said_of_a_change(make_run):
    _, fake = await run(make_run, vision=("test-model", "vision-1"))

    assert "answer_model_switched" not in kinds(fake) and "image_reading_started" in kinds(fake)


async def test_with_no_model_that_reads_images_the_answer_says_so_plainly_and_loses_no_call(make_run):
    result, fake = await run(make_run, vision=())

    assert "aucun modèle capable de lire les images" in result["answer"]
    assert len(fake.llm_calls) == 1 and getattr(fake, "image_requests", []) == []  # only the plan was called


async def test_images_that_are_gone_are_said_to_be_so(make_run):
    graph, fake = make_run(VDBS, router(NO_QUERY))
    fake.vision_models = ["vision-1"]
    fake.run_images = {}  # the backend no longer has them
    state = initial_state("Que dit ce tableau ?", images=[IMAGE])

    result = await graph.ainvoke(state, config=_config(state))

    assert "elles ne sont plus disponibles" in result["answer"] and len(fake.llm_calls) == 1


async def test_several_images_are_all_sent_in_order_and_one_that_cannot_be_had_is_left_out(make_run):
    images = (IMAGE, {"id": "img-2", "content_type": "image/jpeg", "current": True}, {**IMAGE, "id": "img-3"})
    graph, fake = make_run(VDBS, router(NO_QUERY, answer="Deux images lues."))
    fake.vision_models = ["vision-1"]
    fake.run_images = {"img-1": (PNG, "image/png"), "img-3": (PNG, "image/jpeg")}  # the second is gone
    state = initial_state("Compare-les", images=list(images))

    await graph.ainvoke(state, config=_config(state))

    parts = answer_call(fake)[1]["content"][1:]
    assert [part["image_url"]["url"].split(";")[0] for part in parts] == ["data:image/png", "data:image/jpeg"]
    assert ("image_reading_started", {"count": 2}) in fake.event_data
