"""The collections a person is used to, in the routing (#286): first in the catalogue and marked for the plan, a few per
cent more in the pre-filter - a tie-breaker that is never a filter, and nothing at all without a memory in use."""

from tests.agent.conftest import initial_state
from tests.agent.test_graph import HR, IT, VDBS, planner_calls, router


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def on(*habits: tuple[str, float]) -> dict:
    return {"state": "on", "items": [], "habits": [{"collection_id": cid, "weight": w} for cid, w in habits]}


def many(count: int = 30) -> list[dict]:
    return [{"id": f"c{i}", "name": f"Collection {i}", "description": "", "parent_id": None} for i in range(count)]


async def plan_prompt(make_run, vdbs, memory: dict | None, hits: list | None = None) -> str:
    graph, fake = make_run(vdbs, router({"mode": "search"}))
    if memory is not None:
        fake.memory = memory
    if hits is not None:
        fake.collection_search_hits = hits
    state = initial_state("Un sujet précis ?")
    await graph.ainvoke(state, config=_config(state))
    return planner_calls(fake)[0][0]["content"] + "\n---\n" + planner_calls(fake)[0][1]["content"]


# --- what the plan is shown ---


async def test_a_habitual_collection_is_first_and_marked_and_the_plan_is_told_it_is_only_a_tie_breaker(make_run):
    prompt = await plan_prompt(make_run, VDBS, on(("col-it", 0.6)))

    assert prompt.index("Support IT") < prompt.index("Procédures RH")
    assert "'habitual': 'yes'" in prompt.split("Support IT")[1].split("}")[0]
    assert "'habitual'" not in prompt.split("Procédures RH")[1].split("}")[0]
    assert "tie-breaker" in prompt and "never leave out one that fits the question better" in prompt


async def test_the_heaviest_habit_comes_first_and_the_others_keep_their_order(make_run):
    vdbs = [*VDBS, {"id": "col-x", "name": "Autre", "description": "", "parent_id": None}]

    prompt = await plan_prompt(make_run, vdbs, on(("col-it", 0.3), ("col-x", 0.9)))

    assert prompt.index("Autre") < prompt.index("Support IT") < prompt.index("Procédures RH")


async def test_without_a_habit_the_plan_is_shown_exactly_what_it_was(make_run):
    with_none = await plan_prompt(make_run, VDBS, on())
    without = await plan_prompt(make_run, VDBS, {"state": "on", "items": []})

    assert with_none.replace("\n---\n", "") != "" and "habitual" not in with_none and "tie-breaker" not in with_none
    assert with_none.index("Procédures RH") < with_none.index("Support IT") and with_none == without


async def test_a_memory_that_is_not_in_use_gives_the_routing_no_habit(make_run):
    for state in ("temporary", "unavailable", "disabled"):
        memory = {**on(("col-it", 1.0)), "state": state}

        prompt = await plan_prompt(make_run, VDBS, memory)

        assert "habitual" not in prompt
        assert prompt.index("Procédures RH") < prompt.index("Support IT")


async def test_a_habit_on_a_collection_the_person_cannot_read_is_never_shown(make_run):
    prompt = await plan_prompt(make_run, VDBS, on(("col-secret", 1.0)))

    assert "col-secret" not in prompt and "habitual" not in prompt and "tie-breaker" not in prompt


async def test_the_habits_never_leave_a_collection_out_of_a_small_catalogue(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.memory = on(("col-it", 1.0))
    state = initial_state("Combien de jours de congés ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert {vdb["id"] for vdb in result["catalogue"]} == {HR["id"], IT["id"]}
    assert fake.searched_collection_ids == [["col-hr", "col-it"]]


# --- in the pre-filter ---


def hits(count: int, *, top: float = 0.9) -> list[dict]:
    """`count` collections, c0 the closest: a flat ranking where a few per cent is enough to change the order."""
    return [{"collection_id": f"c{i}", "score": top - 0.001 * i} for i in range(count)]


async def test_a_habit_that_is_about_as_close_as_the_others_gets_into_the_prefilter(make_run):
    ranking = hits(21)  # c20 is the 21st: out without a habit

    without = await plan_prompt(make_run, many(), on(), ranking)
    prefers = await plan_prompt(make_run, many(), on(("c20", 1.0)), ranking)

    assert "Collection 20" not in without and "Collection 19" in without
    assert "Collection 20" in prefers and "Collection 19" not in prefers


async def test_a_habit_that_fits_clearly_worse_does_not_displace_a_collection_that_fits_better(make_run):
    ranking = [*hits(20, top=0.95), {"collection_id": "c20", "score": 0.5}]

    prompt = await plan_prompt(make_run, many(), on(("c20", 1.0)), ranking)

    assert "Collection 20" not in prompt and "Collection 0" in prompt and "Collection 19" in prompt


async def test_the_prefilter_asks_for_a_few_more_candidates_when_there_are_habits_and_no_more_otherwise(make_run):
    graph, fake = make_run(many(), router({"mode": "search"}))
    fake.memory = on(("c20", 1.0), ("c21", 0.5))
    asked: list[int] = []
    original = fake.search_collections

    async def spy(collection_ids, query, limit):
        asked.append(limit)
        return await original(collection_ids, query, limit)

    fake.search_collections = spy
    state = initial_state("Un sujet précis ?")

    await graph.ainvoke(state, config=_config(state))

    assert asked == [22]
    graph, fake = make_run(many(), router({"mode": "search"}))
    fake.search_collections = spy
    asked.clear()
    state = initial_state("Un sujet précis ?")
    await graph.ainvoke(state, config=_config(state))
    assert asked == [20]


async def test_a_collection_the_person_attached_stays_in_the_catalogue_whatever_the_habits(make_run):
    graph, fake = make_run(many(), router({"mode": "search"}))
    fake.memory = on(("c20", 1.0))
    fake.collection_search_hits = hits(21)
    state = initial_state("Un sujet précis ?", pinned_vdb_ids=["c25"])

    await graph.ainvoke(state, config=_config(state))

    assert "Collection 25" in planner_calls(fake)[0][1]["content"]
