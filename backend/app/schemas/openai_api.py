"""The OpenAI-compatible API (#513): what it takes and gives back, in the shape the `openai` SDK reads."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MuffinOptions(BaseModel):
    """What a request may ask of Muffin beyond OpenAI's own parameters, in `extra_body.muffin`."""

    model_config = ConfigDict(extra="forbid")

    # The steps of the agent ("Searching…") in the stream, as `reasoning_content`, never in the text of the answer.
    steps: bool = False
    # The conversation of Muffin to go on with, rather than a throwaway one (also the X-Muffin-Conversation header).
    conversation_id: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[dict[str, Any]] | None = None


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    # What OpenAI clients add that has no meaning here is let through (and ignored): the SDKs send many fields. What
    # changes what the answer is (tools, response_format, n, logprobs…) is refused instead, see the service.
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    stream_options: StreamOptions | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    n: int | None = None
    tools: list[Any] | None = None
    functions: list[Any] | None = None
    tool_choice: Any | None = None
    function_call: Any | None = None
    response_format: dict[str, Any] | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    muffin: MuffinOptions | None = Field(default=None, validation_alias="muffin")


class ModelOut(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str = "muffin"
    # Not OpenAI's: a name to show, for the clients that read one.
    name: str


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelOut]
