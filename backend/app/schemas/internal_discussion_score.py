from pydantic import BaseModel


class ConversationMessageOut(BaseModel):
    role: str
    content: str


class DiscussionScoreCreate(BaseModel):
    message_count: int
    llm_model: str
    coherent: bool
    coherence_issues: list[str] = []
    context_usage_score: float
    context_usage_issues: list[str] = []
    reasoning: str | None = None
