from pydantic_settings import BaseSettings, SettingsConfigDict


class RunSettings(BaseSettings):
    # How many sub-collections a pinned collection brings along with it (#220). Every pinned
    # collection is searched, one index query each, so pinning a collection with a large subtree
    # would slow down every search of the run; the nearest ones (by level) are pinned and the
    # rest is left to the "go further" exploration (#219).
    PINNED_DESCENDANTS_LIMIT: int = 30

    # The live stream of a run (#510): what the chat reads to show the steps and the answer as they come. It is kept for
    # a while after the run, so that a page reloaded in the middle of it picks up from the start; past that, or when the
    # stream cannot be read, the chat asks the run itself.
    RUN_STREAM_TTL_SECONDS: int = 900
    RUN_STREAM_MAXLEN: int = 20000
    # How many streams one user may hold open at once, per pod: each is a connection kept for the length of an answer.
    RUN_STREAMS_PER_USER: int = 8
    # A line sent this often when nothing else is, so that a proxy does not cut a quiet stream and the chat can tell a
    # stream that went silent from one that is only waiting.
    RUN_STREAM_PING_SECONDS: int = 15

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
