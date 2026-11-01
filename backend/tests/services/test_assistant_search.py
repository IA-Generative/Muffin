"""Finding an assistant by its description (#531), with as few calls as it takes: how many calls to the embedding model
and to the index each search makes is what these tests pin down, along with what is - and is never - indexed."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from app.core.security.factory import RequestContext
from app.models.assistant import Assistant
from app.services import assistant_search_service, search_service, vector_store
from app.services.assistant_search_service import HYBRID, LEXICAL, AssistantSearchService, indexed_text

TOPICS = [
    ("congé", "vacances", "repos"),
    ("marché", "achat", "commande"),
    ("juridique", "loi", "décret"),
    ("rapport",),
]


def vector_of(text: str) -> list[float]:
    """A made-up embedding: one axis for each topic, so that 'vacances' is close to 'congés' with no word in common."""
    lowered = text.lower()
    counts = [float(sum(lowered.count(word) for word in words)) for words in TOPICS]
    # Nothing known about a text: its own axis, close to nothing else.
    return [*counts, 0.0] if any(counts) else [*counts, 1.0]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def create(self, model, input):  # noqa: A002
        texts = input if isinstance(input, list) else [input]
        self.calls.append(list(texts))
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=vector_of(t)) for i, t in enumerate(texts)])


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.fixture
def embeddings(monkeypatch):
    fake = FakeEmbeddings()
    monkeypatch.setattr(search_service, "_openai_client", SimpleNamespace(embeddings=fake))
    monkeypatch.setattr(search_service, "async_redis", lambda: FakeRedis_instance)
    monkeypatch.setattr(vector_store, "_client", QdrantClient(":memory:"))

    async def model(_db):
        return "emb-1"

    monkeypatch.setattr(assistant_search_service, "default_embedding_model", model)
    search_service._in_flight.clear()
    FakeRedis_instance.store.clear()
    return fake


FakeRedis_instance = FakeRedis()

USER = RequestContext(user_id="u", email="u@example.test", roles=[], is_admin=False, groups=[])


def assistant(name: str, description: str = "", suggestions: list[str] | None = None, **fields) -> Assistant:
    return Assistant(
        id=uuid.uuid4(),
        owner_id="u",
        name=name,
        description=description,
        suggestions=suggestions or [],
        instructions=fields.pop("instructions", ""),
        collection_ids=fields.pop("collection_ids", []),
        disabled_tools=[],
        consult_assistant_ids=[],
        **fields,
    )


def many(count: int = 10) -> list[Assistant]:
    """Enough assistants to need the hybrid search, the first three about congés, achats and the law."""
    named = [
        assistant("RH", "Pose de vacances et jours de repos"),
        assistant("Achats", "Commandes et procédures de marché public"),
        assistant("Veille", "Textes de loi et décrets"),
    ]
    return named + [assistant(f"Autre {i}", "Sans rapport avec les trois sujets") for i in range(count - 3)]


def service() -> AssistantSearchService:
    return AssistantSearchService(None)  # type: ignore[arg-type]


# --- what is indexed ---


def test_what_an_assistant_says_of_itself_is_indexed_and_never_its_instructions_nor_its_collections():
    mine = assistant(
        "RH",
        "Congés",
        ["Combien de jours ?"],
        instructions="SECRET-DE-FABRICATION",
        collection_ids=[str(uuid.uuid4())],
    )

    text = indexed_text(mine)

    assert "RH" in text and "Congés" in text and "Combien de jours ?" in text
    assert "SECRET-DE-FABRICATION" not in text


# --- a handful of assistants: no call at all ---


async def test_a_handful_of_assistants_is_matched_on_its_words_with_no_call_to_the_model_nor_the_index(embeddings):
    few = [assistant("RH – congés", "Répond sur les congés payés"), assistant("Achats", "Marchés publics")]

    hits = await service().rank(few, "conge")  # no accent, no plural

    assert [(hit.assistant.name, hit.kind) for hit in hits] == [("RH – congés", LEXICAL)]
    assert embeddings.calls == []
    assert vector_store._client.get_collections().collections == []


async def test_a_question_that_matches_no_word_finds_nothing_and_an_empty_one_is_not_a_search(embeddings):
    few = [assistant("RH", "Congés")]

    assert await service().rank(few, "budget") == []
    assert await service().rank(few, "   ") == []
    assert embeddings.calls == []


# --- many assistants: the hybrid search, written once, asked once ---


async def test_many_assistants_are_embedded_in_one_batched_call_then_only_the_question_is(embeddings):
    candidates = many()

    first = await service().rank(candidates, "vacances")
    second = await service().rank(candidates, "commande")

    # 10 descriptions in ONE call, then one call for each new question - none for the descriptions again.
    assert len(embeddings.calls[0]) == 10 and len(embeddings.calls) == 3
    assert embeddings.calls[1:] == [["vacances"], ["commande"]]
    assert first[0].assistant.name == "RH" and first[0].kind == HYBRID
    assert second[0].assistant.name == "Achats"


async def test_the_same_question_asked_again_costs_no_call_at_all(embeddings):
    candidates = many()
    await service().rank(candidates, "vacances")
    before = len(embeddings.calls)

    await service().rank(candidates, "vacances")

    assert len(embeddings.calls) == before


async def test_a_question_searched_in_several_places_at_once_is_embedded_once(embeddings):
    results = await asyncio.gather(*(search_service.embed_query("emb-1", "même question") for _ in range(5)))

    assert embeddings.calls == [["même question"]]
    assert all(result == results[0] for result in results)


async def test_the_embedding_cache_can_be_turned_off(embeddings, monkeypatch):
    monkeypatch.setattr(search_service._search_settings, "SEARCH_EMBEDDING_CACHE_SECONDS", 0)

    await search_service.embed_query("emb-1", "q")
    await search_service.embed_query("emb-1", "q")

    assert len(embeddings.calls) == 2


async def test_only_what_changed_is_embedded_again(embeddings):
    candidates = many()
    await service().rank(candidates, "vacances")
    embeddings.calls.clear()

    candidates[1].description = "Marchés publics et achats, seuils"  # said differently
    candidates[0].instructions = "Nouvelles consignes"  # not indexed: changes nothing
    await service().rank(candidates, "achat")

    assert embeddings.calls[0] == [indexed_text(candidates[1])] and len(embeddings.calls) == 2


async def test_another_embedding_model_makes_every_point_again(embeddings, monkeypatch):
    candidates = many()
    await service().rank(candidates, "vacances")
    embeddings.calls.clear()

    async def other(_db):
        return "emb-2"

    monkeypatch.setattr(assistant_search_service, "default_embedding_model", other)
    await service().rank(candidates, "vacances")

    assert len(embeddings.calls[0]) == 10


# --- embedded as it is written ---


async def test_an_assistant_is_embedded_when_it_is_written_and_not_again_when_nothing_it_says_changed(embeddings):
    mine = assistant("RH", "Congés payés")

    await service().index(mine)
    await service().index(mine)  # same text, same model: nothing to do
    mine.instructions = "Ton chaleureux"
    await service().index(mine)

    assert embeddings.calls == [[indexed_text(mine)]]
    assert vector_store.get_assistant_points([mine.id])[mine.id][1] == "emb-1"


async def test_what_an_assistant_says_changing_embeds_it_again(embeddings):
    mine = assistant("RH", "Congés payés")
    await service().index(mine)

    mine.description = "Congés payés et RTT"
    await service().index(mine)

    assert len(embeddings.calls) == 2


async def test_an_embedding_model_that_is_down_never_fails_a_write_and_the_next_search_writes_the_point(
    embeddings, monkeypatch
):
    mine = assistant("RH", "Congés payés")

    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    await service().index(mine)  # must not raise

    assert vector_store.get_assistant_points([mine.id]) == {}


async def test_a_search_with_the_embedding_model_down_goes_on_with_the_words(embeddings, monkeypatch):
    candidates = many()

    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    hits = await service().rank(candidates, "vacances")

    assert [hit.kind for hit in hits] == [LEXICAL] * len(hits) and hits[0].assistant.name == "RH"


# --- suggesting ---


async def test_only_an_assistant_that_fits_is_suggested_and_a_question_about_nothing_suggests_none(embeddings):
    candidates = many()
    mine = service()

    async def readable(_user):
        return candidates

    mine.readable = readable  # type: ignore[method-assign]

    fits = await mine.suggest(USER, "je voudrais poser des vacances", limit=3)
    nothing = await mine.suggest(USER, "quelle heure est-il", limit=3)

    assert [hit.assistant.name for hit in fits] == ["RH"]
    assert nothing == []


# --- consulting: choosing among candidates ---


async def test_up_to_the_maximum_every_candidate_is_kept_with_no_search(embeddings):
    candidates = many(4)

    kept = await service().closest(candidates, "n'importe quoi", maximum=5)

    assert kept == candidates and embeddings.calls == []


async def test_more_than_the_maximum_keeps_the_closest_ones(embeddings):
    candidates = many(10)

    kept = await service().closest(candidates, "vacances", maximum=2)

    assert len(kept) == 2 and kept[0].name == "RH"
