import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.discussion_score import DiscussionScore
from app.models.message import Message, MessageRole

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(DiscussionScore))
        await session.execute(delete(Message))
        await session.execute(delete(Conversation))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _create_conversation_with_messages() -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id="dev-user", title="Test")
        session.add(conversation)
        await session.flush()
        # Explicit, strictly increasing timestamps: list_messages orders by created_at alone
        # (see ConversationRepository.list_messages), which real usage never collides on since a
        # user's turns are always sent seconds apart - inserting all four in one batch here would
        # otherwise land them all at the same server-side now() and make ordering ambiguous.
        base = datetime.now(UTC)
        session.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content="What is the policy?",
                    created_at=base,
                ),
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    content="2 days/week.",
                    created_at=base + timedelta(seconds=1),
                ),
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content="And for managers?",
                    created_at=base + timedelta(seconds=2),
                ),
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    content="Same policy.",
                    created_at=base + timedelta(seconds=3),
                ),
            ]
        )
        await session.commit()
        return conversation.id


async def test_list_conversation_messages_oldest_first(client):
    conversation_id = await _create_conversation_with_messages()

    response = await client.get(f"/api/internal/conversations/{conversation_id}/messages", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert [m["role"] for m in body] == ["user", "assistant", "user", "assistant"]
    assert body[0]["content"] == "What is the policy?"
    assert body[3]["content"] == "Same policy."


async def test_list_conversation_messages_unknown_conversation_returns_404(client):
    response = await client.get(f"/api/internal/conversations/{uuid.uuid4()}/messages", headers=_headers())
    assert response.status_code == 404


async def test_create_discussion_score_persists_it(client):
    conversation_id = await _create_conversation_with_messages()

    response = await client.post(
        f"/api/internal/conversations/{conversation_id}/discussion-scores",
        headers=_headers(),
        json={
            "message_count": 4,
            "llm_model": "test-model",
            "coherent": False,
            "coherence_issues": ["Second answer contradicts the first."],
            "context_usage_score": 0.5,
            "context_usage_issues": ["Follow-up didn't resolve 'managers' against the policy topic."],
            "reasoning": "One contradiction found.",
        },
    )

    assert response.status_code == 201
    score_id = uuid.UUID(response.json()["id"])

    async with async_session_factory() as session:
        score = await session.get(DiscussionScore, score_id)
        assert score is not None
        assert score.conversation_id == conversation_id
        assert score.message_count == 4
        assert score.coherent is False
        assert score.coherence_issues == ["Second answer contradicts the first."]
        assert score.context_usage_score == 0.5


async def test_create_discussion_score_unknown_conversation_returns_404(client):
    response = await client.post(
        f"/api/internal/conversations/{uuid.uuid4()}/discussion-scores",
        headers=_headers(),
        json={
            "message_count": 0,
            "llm_model": "test-model",
            "coherent": True,
            "context_usage_score": 1.0,
        },
    )
    assert response.status_code == 404
