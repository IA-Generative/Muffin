from pydantic import BaseModel


class LlmModel(BaseModel):
    id: str


class LlmModelsResponse(BaseModel):
    models: list[LlmModel]
