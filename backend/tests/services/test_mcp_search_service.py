"""The MCP search tools (#467): collections proposed for a question, and a question split and searched by
sub-question, in the collections the caller can read, with sources and no answer."""

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.document import Document, DocumentType
from app.models.qa import QaOrigin, QaPair
from app.services import mcp_search_service
from app.services.mcp_search_service import McpSearchService, NoAccessibleCollectionError
from app.services.search_service import SearchService
from app.services.usage_service import UsageService

USER = RequestContext(user_id="u", email="u@example.test", roles=[], is_admin=False)


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _collection(session, name, *, owner="u", description="", parent=None) -> Collection:
    collection = Collection(
        owner_id=owner,
        name=name,
        description=description,
        parent_id=parent.id if parent else None,
        visibility=CollectionVisibility.PRIVATE,
    )
    collection.settings = CollectionSettings(embedding_model="bge")
    session.add(collection)
    await session.flush()
    return collection


async def _document(session, collection, name="doc.pdf", summary=None) -> Document:
    document = Document(collection_id=collection.id, name=name, type=DocumentType.FILE, summary=summary)
    session.add(document)
    await session.flush()
    return document


class Llm:
    """The chat model that splits the question: records what it was asked and answers `reply`."""

    def __init__(self, reply: str) -> None:
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, model, messages):
        self.calls.append((model, messages))
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4)
        )


@pytest.fixture
def llm(monkeypatch):
    fake = Llm(json.dumps(["congés", "télétravail"]))
    monkeypatch.setattr(mcp_search_service, "_openai_client", fake)

    async def default_model():
        return "hub-chat"

    monkeypatch.setattr(mcp_search_service.chat_model_lookup, "default_chat_model", default_model)

    async def record(self, *args, **kwargs):
        fake.recorded = args

    monkeypatch.setattr(UsageService, "record", record)
    return fake


@pytest.fixture
def searches(monkeypatch):
    """Which collections each sub-question was matched to, and searched in; both can be set by a test."""
    state = {"by_description": {}, "points": {}, "searched": []}

    async def search_collections(self, ids, query, limit):
        return [(c, s) for c, s in state["by_description"].get(query, []) if c in ids][:limit]

    async def search_points(self, ids, query, limit):
        state["searched"].append((query, list(ids), limit))
        return [(p, c, s) for p, c, s in state["points"].get(query, []) if c in ids][:limit]

    monkeypatch.setattr(SearchService, "search_collections", search_collections)
    monkeypatch.setattr(SearchService, "search_points", search_points)
    return state


async def test_suggested_collections_come_with_their_path_and_description_best_first(searches):
    async with async_session_factory() as session:
        root = await _collection(session, "RH", description="Ressources humaines")
        leaf = await _collection(session, "Congés", description="Poser des congés", parent=root)
        other = await _collection(session, "Budget")
        await session.commit()
        searches["by_description"]["congés"] = [(leaf.id, 0.9), (other.id, 0.4)]

        result = await McpSearchService(session).suggest_collections(USER, "congés", limit=5)

    assert [(c.name, c.path, c.description, c.score) for c in result.collections] == [
        ("Congés", ["RH", "Congés"], "Poser des congés", 0.9),
        ("Budget", ["Budget"], "", 0.4),
    ]
    assert result.collections[0].url == f"http://localhost:5173/collections/{leaf.id}"


async def test_the_path_leaves_out_an_ancestor_the_caller_cannot_read(searches):
    async with async_session_factory() as session:
        root = await _collection(session, "Secret", owner="someone-else")
        leaf = await _collection(session, "Partagée", parent=root)
        await session.commit()
        searches["by_description"]["q"] = [(leaf.id, 0.5)]

        result = await McpSearchService(session).suggest_collections(USER, "q", limit=None)

    assert result.collections[0].path == ["Partagée"]


async def test_a_collection_the_caller_cannot_read_is_never_suggested(searches):
    async with async_session_factory() as session:
        mine = await _collection(session, "Mine")
        theirs = await _collection(session, "Theirs", owner="someone-else")
        await session.commit()
        searches["by_description"]["q"] = [(mine.id, 0.5), (theirs.id, 0.9)]

        result = await McpSearchService(session).suggest_collections(USER, "q", limit=5)

    assert [c.name for c in result.collections] == ["Mine"]


async def test_the_number_of_suggestions_is_bounded(searches, monkeypatch):
    seen = []

    async def search_collections(self, ids, query, limit):
        seen.append(limit)
        return []

    monkeypatch.setattr(SearchService, "search_collections", search_collections)
    async with async_session_factory() as session:
        service = McpSearchService(session)
        await service.suggest_collections(USER, "q", limit=None)
        await service.suggest_collections(USER, "q", limit=500)
        await service.suggest_collections(USER, "q", limit=0)

    assert seen == [5, 20, 1]


async def test_the_question_is_split_and_each_sub_question_has_its_collections_and_sources(llm, searches):
    async with async_session_factory() as session:
        conges = await _collection(session, "Congés", description="Les congés")
        remote = await _collection(session, "Télétravail", description="Le télétravail")
        document = await _document(session, conges, "conges.pdf")
        chunk = Chunk(
            document_id=document.id,
            index=0,
            text="Dix jours par an",
            token_count=4,
            extras={"page_start": 3, "page_end": 3},
        )
        remote_doc = await _document(session, remote, "teletravail.pdf", summary="La charte du télétravail")
        session.add(chunk)
        await session.flush()
        await session.commit()
        searches["by_description"] = {"congés": [(conges.id, 0.9)], "télétravail": [(remote.id, 0.8)]}
        searches["points"] = {
            "congés": [(chunk.id, conges.id, 0.7)],
            "télétravail": [(remote_doc.id, remote.id, 0.6)],
        }

        result = await McpSearchService(session).search(USER, "congés et télétravail", None, None, None, None, None)

    assert result.model == "hub-chat"
    assert [sub.text for sub in result.sub_queries] == ["congés", "télétravail"]
    first, second = result.sub_queries
    assert [c.name for c in first.collections] == ["Congés"]
    assert [(s.kind, s.text, s.document_name, s.page, s.collection_name, s.score) for s in first.sources] == [
        ("chunk", "Dix jours par an", "conges.pdf", 3, "Congés", 0.7)
    ]
    assert [(s.kind, s.text, s.document_name, s.page) for s in second.sources] == [
        ("summary", "La charte du télétravail", "teletravail.pdf", None)
    ]
    # Each source links to its document in Muffin, whichever client asked.
    assert first.sources[0].url == f"http://localhost:5173/collections/{conges.id}/documents/{document.id}"
    assert second.sources[0].url == f"http://localhost:5173/collections/{remote.id}/documents/{remote_doc.id}"
    assert llm.calls[0][0] == "hub-chat"
    assert "at most 4" in llm.calls[0][1][0]["content"]


async def test_a_qa_pair_is_returned_with_its_question_answer_and_document(llm, searches):
    llm.reply = json.dumps(["congés"])
    async with async_session_factory() as session:
        collection = await _collection(session, "Congés", description="Les congés")
        document = await _document(session, collection, "conges.pdf")
        pair = QaPair(
            collection_id=collection.id,
            document_id=document.id,
            question="Combien de jours ?",
            answer="Dix",
            origin=QaOrigin.GENERATED,
        )
        session.add(pair)
        await session.flush()
        await session.commit()
        searches["by_description"]["congés"] = [(collection.id, 0.9)]
        searches["points"]["congés"] = [(pair.id, collection.id, 0.8)]

        result = await McpSearchService(session).search(USER, "congés", None, None, None, None, None)

    (source,) = result.sub_queries[0].sources
    assert (source.kind, source.text, source.document_name) == ("qa", "Combien de jours ?\nDix", "conges.pdf")


async def test_given_collections_are_the_only_ones_searched_for_every_sub_question(llm, searches):
    async with async_session_factory() as session:
        wanted = await _collection(session, "Wanted")
        await _collection(session, "Other")
        await session.commit()

        result = await McpSearchService(session).search(USER, "a et b", [wanted.id], None, None, None, None)

    assert [(query, ids) for query, ids, _ in searches["searched"]] == [
        ("congés", [wanted.id]),
        ("télétravail", [wanted.id]),
    ]
    assert all([c.name for c in sub.collections] == ["Wanted"] for sub in result.sub_queries)


async def test_a_collection_the_caller_cannot_read_is_refused_not_searched(llm, searches):
    async with async_session_factory() as session:
        mine = await _collection(session, "Mine")
        theirs = await _collection(session, "Theirs", owner="someone-else")
        await session.commit()

        with pytest.raises(NoAccessibleCollectionError):
            await McpSearchService(session).search(USER, "q", [mine.id, theirs.id], None, None, None, None)
        with pytest.raises(NoAccessibleCollectionError):
            await McpSearchService(session).search(USER, "q", [uuid.uuid4()], None, None, None, None)

    assert searches["searched"] == []
    assert llm.calls == []


async def test_the_bounds_are_the_defaults_when_nothing_is_asked_and_never_over_the_ceilings(llm, searches):
    llm.reply = json.dumps([f"q{i}" for i in range(20)])
    async with async_session_factory() as session:
        service = McpSearchService(session)
        default = await service.search(USER, "q", None, None, None, None, None)
        capped = await service.search(USER, "q", None, None, 100, 100, 100)
        one = await service.search(USER, "q", None, None, 1, None, 2)

    assert len(default.sub_queries) == 4 and {limit for _, _, limit in searches["searched"][:4]} == {5}
    assert len(capped.sub_queries) == 8 and {limit for _, _, limit in searches["searched"][4:12]} == {20}
    assert [sub.text for sub in one.sub_queries] == ["q"] and searches["searched"][-1][2] == 2
    # One sub-question: no need to ask a model to split it.
    assert len(llm.calls) == 2


async def test_the_collections_per_sub_question_are_bounded(llm, searches, monkeypatch):
    seen = []

    async def search_collections(self, ids, query, limit):
        seen.append(limit)
        return []

    monkeypatch.setattr(SearchService, "search_collections", search_collections)
    async with async_session_factory() as session:
        await McpSearchService(session).search(USER, "q", None, None, 2, 2, None)
        await McpSearchService(session).search(USER, "q", None, None, 2, 99, None)

    assert seen == [2, 2, 10, 10]


@pytest.mark.parametrize("reply", ["not json", '{"a": 1}', "[]", "[1, 2]", '["  "]'])
async def test_a_split_that_fails_leaves_the_question_whole(llm, searches, reply):
    llm.reply = reply
    async with async_session_factory() as session:
        result = await McpSearchService(session).search(USER, "ma question", None, None, None, None, None)

    assert [sub.text for sub in result.sub_queries] == ["ma question"]


async def test_a_model_that_errors_leaves_the_question_whole(llm, searches, monkeypatch):
    async def broken(model, messages):
        raise RuntimeError("hub down")

    monkeypatch.setattr(llm.chat.completions, "create", broken)
    async with async_session_factory() as session:
        result = await McpSearchService(session).search(USER, "ma question", None, None, None, None, None)

    assert ([sub.text for sub in result.sub_queries], result.model) == (["ma question"], None)


async def test_a_fenced_reply_is_read_and_duplicates_dropped(llm, searches):
    llm.reply = '```json\n["a", "b", "a"]\n```'
    async with async_session_factory() as session:
        result = await McpSearchService(session).search(USER, "q", None, "my-model", None, None, None)

    assert [sub.text for sub in result.sub_queries] == ["a", "b"]
    assert llm.calls[0][0] == "my-model"


async def test_a_point_postgres_no_longer_knows_is_dropped(llm, searches):
    llm.reply = '["q"]'
    async with async_session_factory() as session:
        collection = await _collection(session, "C", description="d")
        await session.commit()
        searches["by_description"]["q"] = [(collection.id, 0.9)]
        searches["points"]["q"] = [(uuid.uuid4(), collection.id, 0.9)]

        result = await McpSearchService(session).search(USER, "q", None, None, None, None, None)

    assert result.sub_queries[0].sources == []


async def test_a_question_about_no_document_links_to_its_collection(llm, searches):
    llm.reply = json.dumps(["q"])
    async with async_session_factory() as session:
        collection = await _collection(session, "C", description="d")
        pair = QaPair(
            collection_id=collection.id, question="Quoi ?", answer="Ça.", origin=QaOrigin.GENERATED, document_id=None
        )
        session.add(pair)
        await session.flush()
        await session.commit()
        searches["by_description"]["q"] = [(collection.id, 0.9)]
        searches["points"]["q"] = [(pair.id, collection.id, 0.8)]

        result = await McpSearchService(session).search(USER, "q", None, None, None, None, None)

    (source,) = result.sub_queries[0].sources
    assert (source.document_id, source.url) == (None, f"http://localhost:5173/collections/{collection.id}")
