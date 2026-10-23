import pytest

from app.core.bm25 import Bm25Encoder


@pytest.fixture
def encoder():
    return Bm25Encoder(language="french", k1=1.2, b=0.75, average_length=10)


def test_tokens_are_lowercase_unaccented_stemmed_without_stop_words(encoder):
    assert encoder.tokens("Les Éléphants sont dans la savane") == encoder.tokens("elephants savane")
    assert "les" not in encoder.tokens("les chats")


def test_codes_and_numbers_are_kept(encoder):
    assert encoder.tokens("dossier AB-1234") == encoder.tokens("dossier") + ["ab", "1234"]


def test_the_same_word_gets_the_same_index_everywhere(encoder):
    document, _ = encoder.encode_document("la vitesse des voitures")
    query, _ = encoder.encode_query("vitesse")
    assert query[0] in document


def test_a_repeated_term_saturates_instead_of_growing_linearly(encoder):
    _, once = encoder.encode_document("chat " + "x " * 9)
    _, many = encoder.encode_document("chat " * 5 + "x " * 5)
    ratio = many[0] / once[0]
    assert 1 < ratio < 5


def test_a_longer_text_weighs_each_term_less(encoder):
    _, short = encoder.encode_document("chat noir")
    _, long = encoder.encode_document("chat " + "mot " * 40)
    assert short[0] > long[0]


def test_a_query_is_one_per_distinct_term(encoder):
    indices, values = encoder.encode_query("chat chat chien")
    assert len(indices) == 2
    assert values == [1.0, 1.0]


def test_a_text_of_stop_words_only_has_no_vector(encoder):
    assert encoder.encode_document("le la les") == ([], [])
    assert encoder.encode_query("le la les") == ([], [])
