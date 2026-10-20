import uuid

import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.collection import Collection
from app.services.search_service import SearchService

OWNER_ID = "user-a"


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _create(name: str, parent_id: uuid.UUID | None = None) -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id=OWNER_ID, name=name, parent_id=parent_id)
        session.add(collection)
        await session.commit()
        return collection.id


async def _tree() -> dict[str, uuid.UUID]:
    root = await _create("Root")
    child = await _create("Child", root)
    grandchild = await _create("Grandchild", child)
    sibling = await _create("Sibling", root)
    unrelated = await _create("Unrelated")
    return {"root": root, "child": child, "grandchild": grandchild, "sibling": sibling, "unrelated": unrelated}


def _names(path) -> list[str]:
    return [item.name for item in path]


class TestResolveScope:
    async def test_never_widens_unless_asked(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            scope = await SearchService(session).resolve_scope([tree["root"]], include_descendants=False)

        assert scope == [tree["root"]]

    async def test_includes_every_level_below_and_nothing_beside(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            scope = await SearchService(session).resolve_scope([tree["child"]], include_descendants=True)

        assert set(scope) == {tree["child"], tree["grandchild"]}

    async def test_overlapping_subtrees_count_once(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            scope = await SearchService(session).resolve_scope(
                [tree["root"], tree["child"], tree["unrelated"]], include_descendants=True
            )

        assert sorted(scope) == sorted(tree.values())


class TestCollectionPaths:
    async def test_path_runs_from_the_requested_collection_down_to_the_result(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            paths = await SearchService(session).collection_paths({tree["grandchild"]}, [tree["root"]])

        assert _names(paths[tree["grandchild"]]) == ["Root", "Child", "Grandchild"]

    async def test_path_never_goes_above_the_requested_collections(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            paths = await SearchService(session).collection_paths({tree["grandchild"]}, [tree["child"]])

        assert _names(paths[tree["grandchild"]]) == ["Child", "Grandchild"]

    async def test_highest_requested_collection_wins(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            paths = await SearchService(session).collection_paths({tree["grandchild"]}, [tree["child"], tree["root"]])

        assert _names(paths[tree["grandchild"]]) == ["Root", "Child", "Grandchild"]

    async def test_a_result_in_a_requested_collection_is_just_itself(self, cleanup):
        tree = await _tree()

        async with async_session_factory() as session:
            paths = await SearchService(session).collection_paths({tree["child"]}, [tree["child"]])

        assert _names(paths[tree["child"]]) == ["Child"]
