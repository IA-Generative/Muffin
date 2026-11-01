import uuid
from typing import Literal

from pydantic import BaseModel, Field


class SuggestedCollection(BaseModel):
    """A collection that looks relevant to a question."""

    id: uuid.UUID
    name: str
    path: list[str] = Field(description="Names from the top of the tree down to the collection that you may read")
    description: str
    score: float = Field(description="How close the collection's description is to the question, higher is closer")
    url: str = Field(description="Where to open the collection in Muffin")


class SuggestedCollections(BaseModel):
    query: str
    collections: list[SuggestedCollection]


class SearchSource(BaseModel):
    """One passage found: what it is, where it comes from and how close it is to the question."""

    kind: Literal["chunk", "qa", "summary"] = Field(
        description="A passage of a document, a question already answered about it, or the summary of the document"
    )
    text: str = Field(description="The passage, the question with its answer, or the summary")
    score: float = Field(description="Cosine similarity with the question, comparable across collections")
    rerank_score: float | None = Field(
        default=None,
        description="What the reranking model rated the passage for the question, when the search was reranked: the "
        "sources are then in the order of this rating, `score` staying the cosine",
    )
    document_id: uuid.UUID | None = Field(description="None for a question about the collection as a whole")
    document_name: str | None
    page: int | None = Field(description="The first page the passage is on, when it is known")
    collection_id: uuid.UUID
    collection_name: str
    url: str = Field(description="Where to open the document in Muffin, or its collection when it has no document")


class SubQueryResult(BaseModel):
    text: str = Field(description="The sub-question")
    collections: list[SuggestedCollection] = Field(description="The collections searched for it")
    sources: list[SearchSource] = Field(description="Best first")


class SearchResult(BaseModel):
    query: str
    model: str | None = Field(description="The model that split the question, None if it was not split")
    sub_queries: list[SubQueryResult]
