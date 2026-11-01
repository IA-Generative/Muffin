from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    # Whether anyone may make an assistant public in the organisation (#514). Off: only a platform administrator can,
    # and an administrator can always take a public assistant down.
    ASSISTANTS_PUBLIC_ENABLED: bool = False
    # How many assistants a person may author.
    ASSISTANTS_PER_USER: int = 100
    # With fewer assistants than this to look through, they are matched on their words, here, with no call to an
    # embedding model nor to the index: a handful of assistants needs no vector. From this many, the hybrid search runs.
    ASSISTANTS_SEARCH_INDEX_MIN: int = 8
    # The most a search answers with, and the least score (cosine) a suggestion needs to be made at all.
    ASSISTANTS_SEARCH_LIMIT: int = 20
    ASSISTANTS_SUGGEST_MIN_SCORE: float = 0.45
    # How many other assistants an assistant may consult for one question (#531): when it may consult more than this,
    # the ones whose description is closest to the question are kept, and when it may consult this many or fewer, all
    # are - with no search at all.
    ASSISTANTS_CONSULT_MAX: int = 5

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
