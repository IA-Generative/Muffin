"""Multiple-choice questions the assistant asks instead of answering (#344): kept with its message,
answered by the next run, abandoned if the user writes something else."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.run import Run
from app.models.task import Task

API_KEY = "test-worker-key"

QUESTIONS = [
    {
        "question": "Quelle période voulez-vous ?",
        "header": "Période",
        "multi_select": False,
        "options": [
            {"label": "2023", "description": "Année dernière"},
            {"label": "2024", "description": "Cette année"},
        ],
    },
    {
        "question": "Quels services ?",
        "header": "Services",
        "multi_select": True,
        "options": [{"label": "RH", "description": ""}, {"label": "Finance", "description": ""}],
    },
]


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.commit()


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False, groups=[]
        )

    return override


async def _run(client, query: str, **extra) -> dict:
    with patch("app.services.run_service.enqueue_run_agent", return_value=f"celery-{uuid.uuid4()}"):
        response = await client.post("/api/runs", json={"query": query, **extra})
    assert response.status_code == 202, response.text
    return response.json()


async def _ask(client, run: dict, questions: list[dict] | None = QUESTIONS) -> None:
    body = {"answer": "Quelle période voulez-vous ?\n- 2023\n- 2024", "questions": questions}
    response = await client.patch(f"/api/internal/runs/{run['id']}/result", json=body, headers={"X-API-Key": API_KEY})
    assert response.status_code == 200, response.text


async def _messages(client, conversation_id: str) -> list[dict]:
    return (await client.get(f"/api/conversations/{conversation_id}/messages")).json()


async def test_the_questions_are_kept_on_the_assistant_message(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)

    user_message, assistant = await _messages(client, run["conversation_id"])

    assert user_message["questions"] is None
    assert assistant["questions"][0]["header"] == "Période"
    assert assistant["questions"][1]["multi_select"] is True
    assert assistant["questions_answer"] is None
    assert assistant["questions_abandoned"] is False


async def test_a_question_without_options_is_a_free_text_question(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run, [{"question": "Pour quelle année ?", "header": "Précision"}])

    assistant = (await _messages(client, run["conversation_id"]))[1]

    assert assistant["questions"][0]["options"] == []


async def test_a_run_with_no_questions_is_unchanged(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run, None)

    assistant = (await _messages(client, run["conversation_id"]))[1]

    assert assistant["questions"] is None and assistant["questions_abandoned"] is False


async def test_the_answer_is_kept_with_the_questions_and_starts_a_run(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    answer = await _run(
        client,
        "Période : 2024 ; Services : RH, Finance",
        conversation_id=run["conversation_id"],
        answers_run_id=assistant["run_id"],
        answers=[{"selected": ["2024"]}, {"selected": ["RH", "Finance"], "text": " pas la direction "}],
    )

    messages = await _messages(client, run["conversation_id"])
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert messages[1]["questions_answer"] == [
        {"selected": ["2024"], "text": None},
        {"selected": ["RH", "Finance"], "text": "pas la direction"},
    ]
    assert messages[1]["questions_abandoned"] is False
    assert answer["query"].startswith("Période")


async def test_a_free_text_answer_is_enough(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    await _run(
        client,
        "Autre chose",
        conversation_id=run["conversation_id"],
        answers_run_id=assistant["run_id"],
        answers=[{"text": "la période d'avant"}, {"selected": ["RH"]}],
    )

    answered = (await _messages(client, run["conversation_id"]))[1]["questions_answer"]
    assert answered[0] == {"selected": [], "text": "la période d'avant"}


@pytest.mark.parametrize(
    "answers",
    [
        [{"selected": ["2024"]}],  # one answer missing
        [{"selected": ["1999"]}, {"selected": ["RH"]}],  # not offered
        [{"selected": ["2023", "2024"]}, {"selected": ["RH"]}],  # two for a single choice
        [{"selected": ["2024"]}, {"selected": ["RH", "RH"]}],  # twice the same
        [{"selected": ["2024"]}, {"text": "  "}],  # blank
    ],
)
async def test_answers_that_do_not_fit_the_questions_are_refused(client, answers):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        response = await client.post(
            "/api/runs",
            json={
                "query": "x",
                "conversation_id": run["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": answers,
            },
        )

    assert response.status_code == 422
    assert len(await _messages(client, run["conversation_id"])) == 2


async def test_writing_something_else_abandons_the_questions(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    await _run(client, "Laisse tomber, autre question", conversation_id=run["conversation_id"])

    messages = await _messages(client, run["conversation_id"])
    assert messages[1]["questions_abandoned"] is True
    assert messages[1]["questions_answer"] is None
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        late = await client.post(
            "/api/runs",
            json={
                "query": "x",
                "conversation_id": run["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": [{"selected": ["2024"]}, {"selected": ["RH"]}],
            },
        )
    assert late.status_code == 409


async def test_questions_are_answered_once(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]
    answers = [{"selected": ["2024"]}, {"selected": ["RH"]}]
    await _run(client, "r", conversation_id=run["conversation_id"], answers_run_id=assistant["run_id"], answers=answers)

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        again = await client.post(
            "/api/runs",
            json={
                "query": "r",
                "conversation_id": run["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": answers,
            },
        )

    assert again.status_code == 409


async def test_a_message_without_questions_cannot_be_answered(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run, None)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        response = await client.post(
            "/api/runs",
            json={
                "query": "x",
                "conversation_id": run["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": [],
            },
        )

    assert response.status_code == 409


async def test_questions_of_another_conversation_cannot_be_answered(client):
    first = await _run(client, "Combien de congés ?")
    await _ask(client, first)
    assistant = (await _messages(client, first["conversation_id"]))[1]
    other = await _run(client, "Autre conversation")

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        response = await client.post(
            "/api/runs",
            json={
                "query": "x",
                "conversation_id": other["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": [{"selected": ["2024"]}, {"selected": ["RH"]}],
            },
        )

    assert response.status_code == 409


async def test_the_worker_is_told_which_messages_asked_questions_and_whether_anyone_is_there(client):
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]
    answer = await _run(
        client,
        "Période : 2024",
        conversation_id=run["conversation_id"],
        answers_run_id=assistant["run_id"],
        answers=[{"selected": ["2024"]}, {"selected": ["RH"]}],
        interactive=False,
    )

    response = await client.get(f"/api/internal/runs/{answer['id']}", headers={"X-API-Key": API_KEY})

    body = response.json()
    assert body["interactive"] is False
    assert [(item["role"], item["asked"]) for item in body["history"]] == [("user", False), ("assistant", True)]


async def test_a_run_that_ended_on_questions_reports_them_with_its_status(client):
    run = await _run(client, "Combien de congés ?")
    assert (await client.get(f"/api/runs/{run['id']}")).json()["questions"] is None
    await _ask(client, run)
    async with async_session_factory() as session:
        stored = await session.get(Run, uuid.UUID(run["id"]))
        stored.status = "completed"
        await session.commit()

    body = (await client.get(f"/api/runs/{run['id']}")).json()

    assert [question["header"] for question in body["questions"]] == ["Période", "Services"]


async def test_the_answer_goes_on_with_the_collections_and_web_search_of_the_run_that_asked(client):
    collection_id = str(uuid.uuid4())
    run = await _run(client, "Combien de congés ?", collection_ids=[collection_id], web_search_enabled=True)
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    answer = await _run(
        client,
        "r",
        conversation_id=run["conversation_id"],
        answers_run_id=assistant["run_id"],
        answers=[{"selected": ["2024"]}, {"selected": ["RH"]}],
    )

    async with async_session_factory() as session:
        stored = await session.get(Run, uuid.UUID(answer["id"]))
    assert stored.pinned_collection_ids == [collection_id]
    assert stored.web_search_enabled is True


async def test_questions_asked_to_someone_else_cannot_be_answered(client):
    app.dependency_overrides[get_current_user] = _as_user("owner")
    run = await _run(client, "Combien de congés ?")
    await _ask(client, run)
    assistant = (await _messages(client, run["conversation_id"]))[1]

    app.dependency_overrides[get_current_user] = _as_user("someone-else")
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-x"):
        response = await client.post(
            "/api/runs",
            json={
                "query": "x",
                "conversation_id": run["conversation_id"],
                "answers_run_id": assistant["run_id"],
                "answers": [{"selected": ["2024"]}, {"selected": ["RH"]}],
            },
        )

    assert response.status_code == 404  # the conversation is not theirs
