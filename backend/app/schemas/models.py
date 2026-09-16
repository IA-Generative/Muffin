from pydantic import BaseModel


class ChatModel(BaseModel):
    id: str


class ChatModelsResponse(BaseModel):
    models: list[ChatModel]
