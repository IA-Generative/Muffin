"""Finding the passage a QA pair's answer comes from (#126)."""

import uuid
from types import SimpleNamespace

from app.services.qa_source import find_source


def _chunk(text: str, page: int = 1):
    return SimpleNamespace(id=uuid.uuid4(), text=text, extras={"page_start": page})


def _pair(answer: str, excerpt: str | None = None):
    return SimpleNamespace(answer=answer, source_excerpt=excerpt)


CHUNKS = [
    _chunk(
        "Les congés payés sont de vingt-cinq jours ouvrés par an. Ils se prennent en accord avec le responsable.", 1
    ),
    _chunk(
        "Le télétravail est autorisé deux jours par semaine. Une demande écrite doit être adressée au responsable. "
        "Le matériel est fourni par l'entreprise.",
        4,
    ),
    _chunk("Les frais de déplacement sont remboursés sur justificatifs.", 6),
]


def test_the_chunk_sharing_the_most_words_with_the_answer_is_the_source():
    found = find_source(_pair("Le télétravail est autorisé deux jours par semaine sur demande écrite."), CHUNKS)

    assert found is not None
    chunk, excerpt = found
    assert chunk is CHUNKS[1]
    assert "télétravail" in excerpt


def test_the_passage_is_the_sentences_that_answer_not_the_whole_chunk():
    _, excerpt = find_source(_pair("Le matériel nécessaire est fourni par l'entreprise."), CHUNKS)

    assert "matériel" in excerpt
    assert "Les congés" not in excerpt


def test_an_answer_that_matches_nothing_has_no_source_rather_than_a_guess():
    assert find_source(_pair("Un propos sans aucun rapport avec les extraits disponibles."), CHUNKS) is None


def test_a_few_shared_words_in_a_long_answer_are_not_enough():
    answer = "Le responsable décide librement de nombreuses choses très différentes selon les services concernés."

    assert find_source(_pair(answer), CHUNKS) is None


def test_a_very_short_answer_has_nothing_to_match_on():
    assert find_source(_pair("Oui."), CHUNKS) is None


def test_a_known_excerpt_pins_down_its_chunk_whatever_the_answer_says():
    pair = _pair("Réponse reformulée.", excerpt="Les frais de   déplacement sont remboursés sur justificatifs.")

    chunk, excerpt = find_source(pair, CHUNKS)

    assert chunk is CHUNKS[2]
    assert excerpt == pair.source_excerpt


def test_no_chunks_means_no_source():
    assert find_source(_pair("Le télétravail est autorisé deux jours par semaine."), []) is None
