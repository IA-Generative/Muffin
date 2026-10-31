from app.graph.services.scope import scope_ids, scope_vdbs

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
