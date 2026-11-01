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
