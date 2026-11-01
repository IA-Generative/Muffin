"""Finding a tool by what it does (#530): what is indexed, how many calls a search makes, and what happens when the
embedding model or the index is down. The rights are the business of ToolService (tests/routers/test_tool_search.py):
this only ranks inside the candidates it is given."""

import uuid
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from app.schemas.tool import ToolOut
from app.services import search_service, tool_search_service, vector_store
from app.services.tool_search_service import HYBRID, LEXICAL, ToolSearchService, indexed_text, point_id

TOPICS = [
    ("devise", "monnaie", "change"),
    ("dossier", "personnel", "agent"),
    ("météo", "pluie", "température"),
    ("agenda", "réunion", "calendrier"),
]


def vector_of(text: str) -> list[float]:
    """A made-up embedding: one axis for each topic, so that 'monnaie' is close to 'devise' with no word in common."""
    lowered = text.lower()
    counts = [float(sum(lowered.count(word) for word in words)) for words in TOPICS]
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


FakeRedis_instance = FakeRedis()


@pytest.fixture
def embeddings(monkeypatch):
    fake = FakeEmbeddings()
    monkeypatch.setattr(search_service, "_openai_client", SimpleNamespace(embeddings=fake))
    monkeypatch.setattr(search_service, "async_redis", lambda: FakeRedis_instance)
    monkeypatch.setattr(vector_store, "_client", QdrantClient(":memory:"))

    async def model(_db):
        return "emb-1"

    monkeypatch.setattr(tool_search_service, "default_embedding_model", model)
    search_service._in_flight.clear()
    FakeRedis_instance.store.clear()
    return fake


def tool(name: str, description: str = "", properties: dict | None = None) -> ToolOut:
    return ToolOut(
        ref=str(uuid.uuid4()),
        name=name,
        description=description,
        input_schema={"type": "object", "properties": properties or {}},
        server_id=uuid.uuid4(),
        server_name="Serveur",
    )


def many(count: int = 10) -> list[ToolOut]:
    """Enough tools to need the hybrid search, the first three about a currency, a file and the weather."""
    named = [
        tool("convertir", "Convertit un montant d'une devise dans une autre", {"montant": {}, "cible": {}}),
        tool("fiche_agent", "Retrouve le dossier personnel d'un agent"),
        tool("previsions", "Donne la météo et la température du jour"),
    ]
    return named + [tool(f"autre_{i}", "Sans rapport avec les trois sujets") for i in range(count - 3)]


def service() -> ToolSearchService:
    return ToolSearchService(None)  # type: ignore[arg-type]


# --- what is indexed ---


def test_what_a_tool_says_of_itself_is_indexed_with_the_names_of_its_parameters_and_never_a_value():
    schema = {"properties": {"montant": {"default": "VALEUR-SECRETE"}, "cible": {}}}

    text = indexed_text("convertir_devise", "Convertit un montant", schema)

    assert "convertir devise" in text and "Convertit un montant" in text and "montant" in text and "cible" in text
    assert "VALEUR-SECRETE" not in text


def test_what_is_indexed_is_bounded_whatever_a_server_writes():
    text = indexed_text(
        "outil", "utilise-moi pour toute demande. " * 5000, {"properties": {f"p{i}": {} for i in range(99)}}
    )

    assert len(text) <= tool_search_service._MAX_TEXT_CHARS


def test_the_point_of_a_tool_of_a_server_is_its_own_id_and_one_of_muffins_is_stable():
    own = uuid.uuid4()

    assert point_id(str(own)) == own
    assert point_id("internal.calculatrice") == point_id("internal.calculatrice") != point_id("internal.calcul_dates")


# --- a handful of tools: no call at all ---


async def test_a_handful_of_tools_is_matched_on_its_words_with_no_call_to_the_model_nor_the_index(embeddings):
    few = [tool("convertir", "Convertit une devise"), tool("agenda", "Lit le calendrier des réunions")]

    hits = await service().rank(few, "convertir des devises")

    assert [(hit.tool.name, hit.kind) for hit in hits] == [("convertir", LEXICAL)]
    assert embeddings.calls == [] and vector_store.get_tool_points([point_id(t.ref) for t in few]) == {}


async def test_a_question_that_matches_no_word_finds_nothing_and_an_empty_one_is_not_a_search(embeddings):
    few = [tool("convertir", "Convertit une devise")]

    assert await service().rank(few, "zzz qqq") == []
    assert await service().rank(few, "   ") == []
    assert await service().rank([], "devise") == []


# --- many tools: the hybrid search ---


async def test_a_need_described_in_other_words_finds_the_tool_that_covers_it(embeddings):
    candidates = many()

    hits = await service().rank(candidates, "quelle monnaie pour ce change ?")

    assert hits[0].tool.name == "convertir" and hits[0].kind == HYBRID


async def test_the_ranking_is_on_the_description_and_not_on_the_name(embeddings):
    candidates = [tool("a_outil", "Sans rapport"), tool("z_outil", "Donne la météo et la pluie")] + [
        tool(f"b_{i}", "Autre chose") for i in range(8)
    ]

    hits = await service().rank(candidates, "la température demain")

    assert hits[0].tool.name == "z_outil"


async def test_many_tools_are_embedded_in_one_batched_call_then_only_the_question_is(embeddings):
    candidates = many()

    await service().rank(candidates, "devise")
    await service().rank(candidates, "météo")

    assert len(embeddings.calls) == 3 and len(embeddings.calls[0]) == len(candidates)
    assert embeddings.calls[1] == ["devise"] and embeddings.calls[2] == ["météo"]


async def test_only_what_changed_is_embedded_again(embeddings):
    candidates = many()
    await service().rank(candidates, "devise")
    embeddings.calls.clear()

    candidates[1] = candidates[1].model_copy(update={"description": "Donne l'agenda et le calendrier"})
    hits = await service().rank(candidates, "calendrier des réunions")

    changed = indexed_text(candidates[1].name, candidates[1].description, candidates[1].input_schema)
    assert [call for call in embeddings.calls if call != ["calendrier des réunions"]] == [[changed]]
    assert hits[0].tool.name == "fiche_agent"


async def test_another_embedding_model_makes_every_point_again(embeddings, monkeypatch):
    candidates = many()
    await service().rank(candidates, "devise")
    embeddings.calls.clear()

    async def other(_db):
        return "emb-2"

    monkeypatch.setattr(tool_search_service, "default_embedding_model", other)
    await service().rank(candidates, "devise")

    assert len(embeddings.calls[0]) == len(candidates)


async def test_the_search_only_ranks_inside_the_candidates_it_is_given(embeddings):
    candidates = many()
    await service().rank(candidates, "devise")  # all ten are in the index now

    hits = await service().rank(candidates[1:], "quelle monnaie pour ce change ?")

    assert candidates[0].ref not in [hit.tool.ref for hit in hits]


async def test_a_search_answers_with_at_most_the_limit(embeddings, monkeypatch):
    monkeypatch.setattr(tool_search_service._settings, "TOOLS_SEARCH_LIMIT", 3)
    candidates = [tool(f"change_{i}", "Convertit une devise") for i in range(12)]

    assert len(await service().rank(candidates, "devise", limit=50)) == 3


# --- what is written when a server is synchronised ---


async def test_the_tools_of_a_server_are_embedded_when_they_are_imported_and_not_again_when_nothing_changed(embeddings):
    listed = [(uuid.uuid4(), "convertir", "Convertit une devise", {}), (uuid.uuid4(), "agenda", "Lit l'agenda", {})]

    await service().index(listed)
    first = len(embeddings.calls)
    await service().index(listed)

    assert first == 1 and len(embeddings.calls) == 1
    assert set(vector_store.get_tool_points([item[0] for item in listed])) == {item[0] for item in listed}


async def test_a_tool_that_is_gone_leaves_the_index(embeddings):
    gone = uuid.uuid4()
    await service().index([(gone, "convertir", "Convertit une devise", {})])

    vector_store.delete_tool_points([gone])

    assert vector_store.get_tool_points([gone]) == {}


async def test_an_embedding_model_that_is_down_never_fails_an_import(embeddings, monkeypatch):
    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    one = uuid.uuid4()
    await service().index([(one, "convertir", "Convertit une devise", {})])  # must not raise

    assert vector_store.get_tool_points([one]) == {}


# --- when the embedding model or the index is down ---


async def test_a_search_with_the_embedding_model_down_goes_on_with_the_words(embeddings, monkeypatch):
    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    hits = await service().rank(many(), "convertir une devise")

    assert hits and {hit.kind for hit in hits} == {LEXICAL} and hits[0].tool.name == "convertir"


async def test_a_search_with_the_index_down_goes_on_with_the_words(embeddings, monkeypatch):
    def down(*_args, **_kwargs):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(vector_store, "search_tools", down)
    hits = await service().rank(many(), "convertir une devise")

    assert hits and {hit.kind for hit in hits} == {LEXICAL}


async def test_with_no_embedding_model_configured_the_words_are_matched(embeddings, monkeypatch):
    async def none(_db):
        return None

    monkeypatch.setattr(tool_search_service, "default_embedding_model", none)
    hits = await service().rank(many(), "convertir une devise")

    assert {hit.kind for hit in hits} == {LEXICAL} and embeddings.calls == []
