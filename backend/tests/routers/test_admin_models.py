import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.app_settings import AppSettings
from app.models.model_profile import ModelProfile
from app.schemas.model_profiles import ModelCapability
from app.services import model_catalog_service

C = ModelCapability
HUB = {
    "small": {C.CHAT},
    "big": {C.CHAT, C.VISION},
    "embed": {C.EMBEDDINGS},
}


@pytest.fixture
async def client(monkeypatch):
    async def hub():
        return {model: set(capabilities) for model, capabilities in HUB.items()}

    monkeypatch.setattr(model_catalog_service, "hub_capabilities", hub)
    app.dependency_overrides[get_current_user] = _as_user(is_admin=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(ModelProfile))
        settings = await session.get(AppSettings, 1)
        if settings is not None:
            settings.classifier_model = None
        await session.commit()


def _as_user(*, is_admin: bool):
    def override() -> RequestContext:
        return RequestContext(
            user_id="user-a",
            email="a@example.com",
            roles=["admin"] if is_admin else ["user"],
            is_admin=is_admin,
        )

    return override


async def test_the_list_is_for_administrators(client):
    app.dependency_overrides[get_current_user] = _as_user(is_admin=False)

    assert (await client.get("/api/admin/models")).status_code == 403
    assert (await client.put("/api/admin/models/small", json={"score": 10})).status_code == 403
    assert (await client.put("/api/admin/models/classifier", json={"classifier_model": "small"})).status_code == 403


async def test_every_model_comes_with_its_capabilities_and_a_default_score(client):
    body = (await client.get("/api/admin/models")).json()

    by_id = {model["id"]: model for model in body["models"]}
    assert by_id["big"]["capabilities"] == ["chat", "vision"]
    assert by_id["embed"]["capabilities"] == ["embeddings"]
    assert by_id["small"] | {"capabilities": None} == {
        "id": "small",
        "capabilities": None,
        "score": 50,
        "description": None,
        "auto_enabled": True,
        "described": False,
    }
    assert body["classifier_model"] is None


async def test_a_model_is_rated_and_the_rating_is_kept(client):
    response = await client.put(
        "/api/admin/models/big", json={"score": 90, "description": "  Hard reasoning  ", "auto_enabled": False}
    )

    assert response.status_code == 200
    assert response.json()["score"] == 90 and response.json()["described"] is True
    listed = {model["id"]: model for model in (await client.get("/api/admin/models")).json()["models"]}
    assert listed["big"]["description"] == "Hard reasoning" and listed["big"]["auto_enabled"] is False
    # What the model can do is not the administrator's to edit.
    assert listed["big"]["capabilities"] == ["chat", "vision"]


async def test_a_score_outside_0_to_100_is_refused(client):
    assert (await client.put("/api/admin/models/small", json={"score": 101})).status_code == 422
    assert (await client.put("/api/admin/models/small", json={"score": -1})).status_code == 422


async def test_an_unknown_model_cannot_be_rated(client):
    assert (await client.put("/api/admin/models/ghost", json={"score": 10})).status_code == 404


async def test_auto_mode_offers_the_chat_models_that_are_enabled_cheapest_first(client):
    await client.put("/api/admin/models/big", json={"score": 90})
    await client.put("/api/admin/models/small", json={"score": 15, "description": "Quick"})
    async with async_session_factory() as session:
        offer = await model_catalog_service.ModelCatalogService(session).auto_candidates()

    assert [(c.model, c.score, c.vision) for c in offer.candidates] == [("small", 15, False), ("big", 90, True)]
    assert offer.classifier_model is None

    await client.put("/api/admin/models/small", json={"score": 15, "auto_enabled": False})
    async with async_session_factory() as session:
        offer = await model_catalog_service.ModelCatalogService(session).auto_candidates()
    assert [c.model for c in offer.candidates] == ["big"]


async def test_the_classifier_must_be_a_chat_model(client):
    assert (await client.put("/api/admin/models/classifier", json={"classifier_model": "embed"})).status_code == 404

    response = await client.put("/api/admin/models/classifier", json={"classifier_model": "small"})

    assert response.json() == {"classifier_model": "small"}
    assert (await client.get("/api/admin/models")).json()["classifier_model"] == "small"
    cleared = await client.put("/api/admin/models/classifier", json={"classifier_model": None})
    assert cleared.json() == {"classifier_model": None}
