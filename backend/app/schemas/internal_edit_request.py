import uuid

from pydantic import BaseModel, Field, field_validator


class EditableDocumentOut(BaseModel):
    """A living document the run's user may change - what the research agent picks its target from."""

    document_id: uuid.UUID
    name: str
    collection_id: uuid.UUID
    collection_name: str
    summary: str | None


class EditRequestCreate(BaseModel):
    document_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()
