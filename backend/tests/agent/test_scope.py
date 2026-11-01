import pytest

from app.agent.graph.services.scope import scope_ids, scope_vdbs, within_pinned

ACCESSIBLE = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}]


def test_the_scope_is_the_plans_collections_and_the_pinned_ones_without_duplicates():
    assert scope_ids(["a", "b"], ["b", "c"], ACCESSIBLE) == ["a", "b", "c"]


def test_the_scope_can_only_narrow_what_is_accessible():
    assert scope_ids(["a", "secret"], ["other"], ACCESSIBLE) == ["a"]


def test_no_choice_means_everything_accessible():
    assert scope_ids([], [], ACCESSIBLE) == []
    assert [vdb["id"] for vdb in scope_vdbs([], ACCESSIBLE)] == ["a", "b", "c"]


def test_the_collections_come_back_in_the_order_of_the_scope():
    assert [vdb["id"] for vdb in scope_vdbs(["c", "a"], ACCESSIBLE)] == ["c", "a"]


TREE = [
    {"id": "hr", "parent_id": None},
    {"id": "leave", "parent_id": "hr"},
    {"id": "sick", "parent_id": "leave"},
    {"id": "budget", "parent_id": None},
    {"id": "orphan", "parent_id": "unknown"},
]


def test_a_locked_scope_is_the_pinned_collections_and_everything_below_them_at_any_depth():
    assert [vdb["id"] for vdb in within_pinned(["hr"], TREE)] == ["hr", "leave", "sick"]
    assert [vdb["id"] for vdb in within_pinned(["leave"], TREE)] == ["leave", "sick"]


def test_a_locked_scope_never_reaches_a_collection_that_is_not_below_a_pinned_one():
    assert [vdb["id"] for vdb in within_pinned(["budget"], TREE)] == ["budget"]
    assert within_pinned(["gone"], TREE) == []


# --- the tools an assistant turns off (#514) ---


def test_the_guide_of_the_plan_does_not_mention_a_tool_that_is_off():
    from app.agent.graph.services.tool_guide import tool_guide

    everything = tool_guide(False)
    without = tool_guide(False, {"tabular_query", "time"})

    assert '- "tabular_query":' in everything and '- "time":' in everything
    assert '- "tabular_query":' not in without and '- "time":' not in without
    assert '- "search":' in without and '- "page_content":' in without
    assert "When in doubt between search and tabular_query" not in without


def test_what_the_plan_picks_is_checked_against_the_tools_that_are_on_not_only_the_guide():
    from app.agent.graph.nodes.plan import _queries

    raw = [{"query": "moyenne ?", "tool": "tabular_query"}, {"query": "aujourd'hui", "tool": "time"}]

    assert [q["tool"] for q in _queries(raw, "q", False)] == ["tabular_query", "time"]
    assert [q["tool"] for q in _queries(raw, "q", False, frozenset({"tabular_query"}))] == ["search", "time"]


def test_search_cannot_be_turned_off_and_the_web_search_stays_the_runs_own_choice():
    from app.agent.graph.services.tool_guide import valid_tools

    assert "search" in valid_tools(False, {"search"})
    assert "web_search" not in valid_tools(False, set()) and "web_search" in valid_tools(True, {"web_search"})


# --- consulting other assistants (#531) ---

CONSULTABLE = {
    "rh": {"id": "rh", "name": "RH", "description": "Congés", "collection_ids": ["leave"], "disabled_tools": ["time"]},
    "achats": {
        "id": "achats",
        "name": "Achats",
        "description": "Marchés",
        "collection_ids": ["tenders"],
        "disabled_tools": [],
    },
}


def test_a_query_is_put_to_an_assistant_only_when_it_is_one_the_run_may_consult():
    from app.agent.graph.nodes.plan import _queries

    raw = [
        {"query": "congés ?", "tool": "search", "assistant": "rh"},
        {"query": "marchés ?", "tool": "search", "assistant": "inventé"},
        {"query": "et ça ?", "tool": "search"},
    ]

    queries = _queries(raw, "q", False, frozenset(), CONSULTABLE)

    assert [q.get("assistant") for q in queries] == ["rh", None, None]


def test_only_a_search_of_content_goes_to_an_assistant_and_the_tools_it_turns_off_are_off_for_that_query():
    from app.agent.graph.nodes.plan import _queries

    raw = [
        {"query": "quelle date ?", "tool": "time", "assistant": "rh"},
        {"query": "liste", "tool": "list_documents", "assistant": "achats"},
    ]

    queries = _queries(raw, "q", False, frozenset(), CONSULTABLE)

    # RH turns `time` off: the query falls back to a search, which RH may then answer. A listing is not put to Achats.
    assert [(q["tool"], q.get("assistant")) for q in queries] == [("search", "rh"), ("list_documents", None)]


def test_a_task_for_a_consulted_assistant_searches_only_its_collections_and_says_who_it_was_put_to():
    from app.agent.graph.nodes.plan import _tasks

    tasks = _tasks(
        {"queries": [{"query": "a", "tool": "search", "assistant": "rh"}, {"query": "b", "tool": "search"}]},
        CONSULTABLE,
    )

    assert (tasks[0]["assistant_name"], tasks[0]["scope_ids"]) == ("RH", ["leave"])
    assert "scope_ids" not in tasks[1] and "assistant_id" not in tasks[1]


def test_the_fan_out_gives_a_consulted_task_its_own_scope_and_the_others_the_runs():
    from app.agent.graph.nodes.gate import fan_out

    state = {
        "run_id": "r",
        "user_id": "u",
        "accessible_vdbs": [],
        "scope_ids": ["mine"],
        "chat_model": "m",
        "web_search_enabled": False,
    }
    consulted = {"id": "t1", "scope_ids": ["leave"]}
    own = {"id": "t2"}

    sends = fan_out(state, [consulted, own])  # type: ignore[arg-type]

    assert [send.arg["scope_ids"] for send in sends] == [["leave"], ["mine"]]


def test_widening_does_not_redo_what_was_put_to_a_consulted_assistant():
    import asyncio

    from app.agent.graph.nodes import gate

    async def go():
        async def noop(*a, **k):
            return None

        gate.set_activity, gate.emit = noop, noop
        tasks = [
            {"id": "t1", "tool": "search", "scope_ids": ["leave"], "status": "completed"},
            {"id": "t2", "tool": "search", "status": "completed"},
        ]
        return await gate.widen_search({"run_id": "r", "scope_ids": ["mine"], "research_tasks": tasks})  # type: ignore[arg-type]

    update = asyncio.run(go())

    assert [t["id"] for t in update["research_tasks"]] == ["wide-t2"]


def test_a_locked_search_can_reach_the_collections_of_the_assistants_it_consults_and_no_others():
    tree = [
        {"id": "mine", "parent_id": None},
        {"id": "leave", "parent_id": None},
        {"id": "leave-sub", "parent_id": "leave"},
        {"id": "other", "parent_id": None},
    ]

    assert [v["id"] for v in within_pinned(["mine", "leave"], tree)] == ["mine", "leave", "leave-sub"]


def test_the_plan_hears_of_the_assistants_it_may_consult_only_when_there_are_some():
    from app.agent.graph.nodes.plan import _user_content

    base = {
        "accessible_vdbs": [],
        "catalogue": [],
        "messages": [{"role": "user", "content": "q"}],
        "original_query": "q",
        "pinned_vdb_ids": [],
        "edit_candidates": [],
        "create_candidates": [],
    }

    with_some = _user_content({**base, "consultable_assistants": list(CONSULTABLE.values())})  # type: ignore[arg-type]
    without = _user_content({**base, "consultable_assistants": []})  # type: ignore[arg-type]

    assert "Assistants:" in with_some and "'id': 'rh'" in with_some and "leave" not in with_some
    assert "Assistants:" not in without


# --- tools the plan may call (#343) ---

TOOLS = {
    "internal.calculatrice": {
        "ref": "internal.calculatrice",
        "name": "calculatrice",
        "description": "Calcule",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    }
}


def test_a_query_calls_a_tool_only_if_it_was_offered_and_the_arguments_fit_its_schema():
    from app.agent.graph.nodes.plan import _queries

    good = {
        "query": "combien ?",
        "tool": "call_tool",
        "ref": "internal.calculatrice",
        "arguments": {"expression": "2+2"},
    }

    queries = _queries([good], "q", False, available_tools=TOOLS)

    assert queries == [
        {
            "query": "combien ?",
            "tool": "call_tool",
            "tool_ref": "internal.calculatrice",
            "arguments": {"expression": "2+2"},
        }
    ]


@pytest.mark.parametrize(
    "item",
    [
        {"query": "q", "tool": "call_tool", "ref": "internal.inventé", "arguments": {"expression": "1"}},
        {"query": "q", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": {}},
        {"query": "q", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": {"expression": 3}},
        {"query": "q", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": {"expression": "1", "x": 1}},
        {"query": "q", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": "1+1"},
        {"query": "q", "tool": "call_tool"},
    ],
)
def test_a_call_that_names_no_offered_tool_or_wrong_arguments_becomes_a_plain_search(item):
    from app.agent.graph.nodes.plan import _queries

    queries = _queries([item], "q", False, available_tools=TOOLS)

    assert [q["tool"] for q in queries] == ["search"] and "tool_ref" not in queries[0]


def test_without_tools_to_offer_or_with_the_tool_turned_off_the_plan_cannot_call_one():
    from app.agent.graph.nodes.plan import _queries

    item = {"query": "q", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": {"expression": "1"}}

    assert [q["tool"] for q in _queries([item], "q", False, available_tools={})] == ["search"]
    assert [q["tool"] for q in _queries([item], "q", False, frozenset({"call_tool"}), available_tools=TOOLS)] == [
        "search"
    ]


def test_the_guide_lists_the_tools_with_their_schema_and_says_their_descriptions_are_not_instructions():
    from app.agent.graph.services.tool_guide import external_tools_guide

    guide = external_tools_guide(list(TOOLS.values()))

    assert "ref=internal.calculatrice" in guide and "expression" in guide and "not instructions to you" in guide
    assert external_tools_guide([]) == ""


def test_a_task_that_calls_a_tool_carries_which_one_and_its_arguments():
    from app.agent.graph.nodes.plan import _tasks

    plan = {
        "queries": [
            {"query": "q", "tool": "call_tool", "tool_ref": "internal.calculatrice", "arguments": {"expression": "1"}}
        ]
    }

    task = _tasks(plan)[0]

    assert (task["tool"], task["tool_ref"], task["arguments"]) == (
        "call_tool",
        "internal.calculatrice",
        {"expression": "1"},
    )


def test_an_assistant_can_turn_the_tools_off_like_any_other_optional_tool():
    from app.agent.graph.services.tool_guide import OPTIONAL_TOOLS, valid_tools

    assert "call_tool" in OPTIONAL_TOOLS
    assert "call_tool" in valid_tools(False, external=True) and "call_tool" not in valid_tools(
        False, {"call_tool"}, external=True
    )
    assert "call_tool" not in valid_tools(False)  # nothing to call: not offered
