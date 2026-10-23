from pydantic_settings import BaseSettings, SettingsConfigDict


class QdrantSettings(BaseSettings):
    QDRANT_URL: str = "http://localhost:6333"
    # None (no key) works against a dev instance started without QDRANT__SERVICE__API_KEY - a real
    # deployment always sets one.
    QDRANT_API_KEY: str | None = None

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


class SearchSettings(BaseSettings):
    """How a hybrid search is run and fused: a dense branch (the embedding) and a sparse lexical branch
    (BM25, IDF computed by Qdrant), merged with Reciprocal Rank Fusion."""

    # RRF: a point ranked r in a branch adds weight / (k + r) to its fused score. The usual 60 flattens the
    # difference between the first ranks; a smaller k favours whichever branch ranks a point first.
    SEARCH_RRF_K: int = 60
    # How much each branch counts in the fusion (1.0 each: neither is favoured).
    SEARCH_DENSE_WEIGHT: float = 1.0
    SEARCH_SPARSE_WEIGHT: float = 1.0
    # Candidates each branch hands to the fusion, before the final limit.
    SEARCH_PREFETCH_LIMIT: int = 50

    # BM25 term-frequency saturation (k1) and length normalisation (b); the average length is in tokens, the
    # length of a typical indexed text (a chunk), since the index has no statistic of it to compute it from.
    SEARCH_BM25_K1: float = 1.2
    SEARCH_BM25_B: float = 0.75
    SEARCH_BM25_AVG_LENGTH: float = 200.0
    # Language of the stemmer and of the stop words applied to the indexed texts and to queries alike - the
    # same one must be used for both, so changing it means re-indexing. A Snowball algorithm name.
    SEARCH_LANGUAGE: str = "french"

    # Logs, for every search, what each branch alone would have ranked (extra queries: debugging only).
    SEARCH_LOG_BRANCHES: bool = False

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
