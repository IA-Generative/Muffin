from pydantic import BaseModel


class AppSettingsOut(BaseModel):
    embedding_model: str | None


class AppSettingsUpdate(BaseModel):
    embedding_model: str
