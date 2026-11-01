from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RerankSettings(BaseSettings):
    """The reranking service (#511): a model that reads the question and each passage together and rates how well the
    passage answers it. Any service that speaks the `/rerank` of Cohere, Jina or vLLM. No URL: reranking is off and
    nothing changes."""

    # The full URL of the route, e.g. https://hub.example/v1/rerank.
    RERANK_API_URL: str = ""
    RERANK_API_KEY: SecretStr = SecretStr("")
    RERANK_MODEL: str = ""
    # How many passages are fetched before they are reranked, when a collection of the search asks for it; the
    # `limit` best are kept.
    RERANK_CANDIDATES: int = 40
    # The longest the search waits for the service before keeping the order it has.
    RERANK_TIMEOUT_SECONDS: float = 3.0
    # A passage longer than this is cut before it is sent (a reranking model reads a few hundred tokens).
    RERANK_PASSAGE_MAX_CHARS: int = 2000

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    @property
    def enabled(self) -> bool:
        return bool(self.RERANK_API_URL.strip())
