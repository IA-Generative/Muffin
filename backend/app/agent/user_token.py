"""The access token of the user a run is for, available to the tools that call a service on that user's behalf.

It lives in memory, for the length of the run, in a context variable: never in the state of the graph (which a
checkpointer writes to Redis), never in an event, a log or the database. A node that needs it asks
`current_user_token()`;
a parallel branch of the research sees it too, the graph copies the context into the threads it starts.

The token is the one the user's request came with: a bearer token, or the access token of their session. It is not
renewed here - a run lasts seconds to minutes, and a tool that finds it expired should say so rather than guess."""

from contextvars import ContextVar

_token: ContextVar[str | None] = ContextVar("agent_user_token", default=None)


def set_user_token(token: str | None) -> None:
    _token.set(token)


def current_user_token() -> str | None:
    return _token.get()
