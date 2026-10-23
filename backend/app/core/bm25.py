"""The sparse lexical vector of a text (BM25), what the hybrid search matches next to the embedding.

Computed here, not by the search engine: the same tokenisation (lowercase, no accents, no stop words,
stemmed) turns a text into a vector at indexing time and a question into one at query time. Qdrant holds
the vectors with its IDF modifier, so it weighs each term by its rarity in the collection itself - what is
sent is only the saturated frequency of each term in the text (the TF part of BM25), and 1.0 per term for a
query."""

import re
import unicodedata
import zlib
from collections import Counter
from functools import lru_cache

from py_rust_stemmers import SnowballStemmer

_TOKEN = re.compile(r"\w+")

_STOP_WORDS = {
    "french": frozenset(
        "au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me meme mes moi mon "
        "ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre "
        "vous c d j l a m n s t y ete etre est sont etait etaient sera seront ai as avons avez ont avait avaient "
        "aura auront cet cette ceux celle celles ci ca cela comme si plus moins tres aussi donc or ni car".split()
    ),
    "english": frozenset(
        "a an and are as at be but by for if in into is it no not of on or such that the their then there these "
        "they this to was will with i you he she we his her its our your were been have has had do does did".split()
    ),
}


def _strip_accents(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _index(token: str) -> int:
    # A stable 32-bit id for a term (Qdrant's sparse indices are u32): the same in every process, which
    # Python's own hash() is not.
    return zlib.crc32(token.encode())


class Bm25Encoder:
    def __init__(self, *, language: str, k1: float, b: float, average_length: float) -> None:
        self.k1 = k1
        self.b = b
        self.average_length = average_length
        self._stop_words = _STOP_WORDS.get(language, frozenset())
        self._stem = lru_cache(maxsize=50_000)(SnowballStemmer(language).stem_word)

    def tokens(self, text: str) -> list[str]:
        words = _TOKEN.findall(_strip_accents(text.lower()))
        return [self._stem(word) for word in words if word not in self._stop_words]

    def encode_document(self, text: str) -> tuple[list[int], list[float]]:
        """(indices, values) of a text to index: per term, tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg))."""
        tokens = self.tokens(text)
        if not tokens:
            return [], []
        norm = self.k1 * (1 - self.b + self.b * len(tokens) / self.average_length)
        weights: dict[int, float] = {}
        for token, count in Counter(tokens).items():
            # Two terms sharing a 32-bit id (a collision) just add up.
            index = _index(token)
            weights[index] = weights.get(index, 0.0) + count * (self.k1 + 1) / (count + norm)
        return list(weights), list(weights.values())

    def encode_query(self, text: str) -> tuple[list[int], list[float]]:
        """(indices, values) of a question: each distinct term once, the IDF is applied by Qdrant."""
        indices = list(dict.fromkeys(_index(token) for token in self.tokens(text)))
        return indices, [1.0] * len(indices)
