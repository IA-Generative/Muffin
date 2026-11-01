"""The generation of images in the chat (#518): off until an administrator turns it on, nothing called before it is
allowed, both answers of the protocol, the image kept by Muffin and read by its owner only, and a key that is never
read back."""

import base64
import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)
from sqlalchemy import delete, func, select

from app.connectors import async_redis
from app.core import secret_store, storage
from app.core.secret_store import LocalProvider
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.image_generation import ImageGenerationSettings
from app.models.message_image import MessageImage
from app.models.stored_secret import StoredSecret
from app.models.token_usage import TokenUsage, TokenUsageKind
from app.repositories.token_usage_repository import TokenUsageRepository
from app.services import image_generation_service
from tests.core.test_image_bytes import jpeg, png, webp_lossless

ALICE, BOB, ROOT = "alice", "bob", "root"
HUB_URL, HUB_KEY = "https://hub.example.test/v1", "hub-secret-key-0000"
OWN_KEY = "-".join(["fake", "provider", "credential"])  # built, so that a scanner does not take it for a real secret
PUBLIC_IMAGE = "https://93.184.216.34/generated/cat.png"
REQUEST = httpx.Request("POST", "https://provider.example.test/v1/images/generations")


def _as(user_id: str, groups: list[str] | None = None, admin: bool = False):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id,
            email=f"{user_id}@example.com",
            roles=["admin"] if admin else ["user"],
            is_admin=admin,
            groups=groups or [],
        )

    return override


def become(user_id: str, groups: list[str] | None = None, admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = _as(user_id, groups, admin)


def status_error(cls, status: int, code: str | None = None):
    body = {"code": code, "message": "PROVIDER-TEXT-THAT-MUST-NOT-LEAK fake-key"} if code else None
    return cls("PROVIDER-TEXT-THAT-MUST-NOT-LEAK", response=httpx.Response(status, request=REQUEST), body=body)


class Provider:
    """The service that makes the images: what it was asked, and what it answers."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.image = png(8, 6)
        self.url: str | None = None
        self.error: Exception | None = None

    def client(self, base_url: str, api_key: str):
        provider = self

        class Images:
            async def generate(self, **kwargs):
                provider.calls.append({"base_url": base_url, "api_key": api_key, **kwargs})
                if provider.error:
                    raise provider.error
                if provider.url:
                    return SimpleNamespace(data=[SimpleNamespace(b64_json=None, url=provider.url)])
                return SimpleNamespace(
                    data=[SimpleNamespace(b64_json=base64.b64encode(provider.image).decode(), url=None)]
                )

        class Client:
            images = Images()

            async def close(self) -> None:
                return None

        return Client()


class Downloads:
    """What the addresses an image may be fetched from answer: the requests made, and the answer."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body = png(4, 4)
        self.headers: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body, headers=self.headers)


@pytest.fixture
def provider(monkeypatch) -> Provider:
    fake = Provider()
    monkeypatch.setattr(image_generation_service, "_client", fake.client)
    return fake


@pytest.fixture
def downloads(monkeypatch) -> Downloads:
    fake = Downloads()
    monkeypatch.setattr(
        image_generation_service,
        "_download_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), follow_redirects=False),
    )
    return fake


@pytest.fixture
def bucket(monkeypatch) -> dict[str, tuple[bytes, str]]:
    objects: dict[str, tuple[bytes, str]] = {}
    monkeypatch.setattr(
        storage, "put_object", lambda key, data, content_type="": objects.update({key: (data, content_type)})
    )
    monkeypatch.setattr(storage, "get_object", lambda key: objects[key])
    monkeypatch.setattr(storage, "delete_objects", lambda keys: [objects.pop(key, None) for key in keys])
    return objects


async def _forget_counters() -> None:
    redis = async_redis()
    for key in await redis.keys("images:*"):
        await redis.delete(key)


@pytest.fixture
async def client(monkeypatch, provider, bucket):
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k1", bytes([1]) * 32)]))
    monkeypatch.setattr(image_generation_service._llm_settings, "OPENAI_API_BASE_URL", HUB_URL)
    monkeypatch.setattr(image_generation_service._llm_settings, "OPENAI_API_KEY", HUB_KEY)
    monkeypatch.setattr(image_generation_service._settings, "IMAGES_PER_USER_PER_MINUTE", 1000)
    await _forget_counters()
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    await _forget_counters()
    async with async_session_factory() as session:
        await session.execute(delete(Conversation))
        await session.execute(delete(ImageGenerationSettings))
        await session.execute(delete(StoredSecret))
        await session.execute(delete(TokenUsage).where(TokenUsage.step == "image_generation"))
        await session.commit()


async def configure(client, **fields) -> dict:
    """Turns the function on as an administrator, with the hub's address and key unless told otherwise."""
    become(ROOT, admin=True)
    body = {"enabled": True, "model": "img-1", **fields}
    response = await client.patch("/api/admin/image-generation", json=body)
    assert response.status_code == 200, response.text
    become(ALICE)
    return response.json()


async def generate(client, prompt="un chat sur un toit", **fields):
    return await client.post("/api/images/generations", json={"prompt": prompt, **fields})


# --- off by default ---


async def test_nothing_is_offered_nor_called_until_an_administrator_turns_it_on(client, provider):
    status = (await client.get("/api/images/status")).json()
    refused = await generate(client)

    assert status["available"] is False
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "fonction_desactivee"
    assert provider.calls == []
    assert (await client.get("/api/conversations")).json()["items"] == []


async def test_turned_on_but_with_no_model_nothing_is_offered(client, provider):
    become(ROOT, admin=True)
    await client.patch("/api/admin/image-generation", json={"enabled": False, "model": ""})
    become(ALICE)

    assert (await client.get("/api/images/status")).json() == {
        "available": False,
        "size": None,
        "daily_limit": None,
        "remaining_today": None,
        "max_prompt_chars": None,
    }


# --- the settings ---


async def test_the_settings_are_the_administrators_only(client):
    assert (await client.get("/api/admin/image-generation")).status_code == 403
    assert (await client.patch("/api/admin/image-generation", json={"enabled": True})).status_code == 403
    assert (await client.post("/api/admin/image-generation/test")).status_code == 403


async def test_a_new_installation_has_the_function_off_and_the_hubs_address(client):
    become(ROOT, admin=True)

    settings = (await client.get("/api/admin/image-generation")).json()

    assert settings["enabled"] is False and settings["uses_hub_address"] is True and settings["ready"] is False
    assert settings["base_url"] == HUB_URL and settings["hub_available"] is True and settings["has_key"] is False
    assert settings["allowed_groups"] == [] and settings["size"] == "1024x1024"


async def test_the_key_is_written_and_never_read_back(client):
    settings = await configure(client, base_url="https://gateway.internal:4000/v1", api_key=OWN_KEY)
    become(ROOT, admin=True)
    again = await client.get("/api/admin/image-generation")

    assert settings["has_key"] is True and settings["uses_hub_address"] is False and settings["ready"] is True
    assert OWN_KEY not in str(settings) and OWN_KEY not in again.text
    async with async_session_factory() as session:
        stored = (await session.execute(select(StoredSecret))).scalars().all()
    assert len(stored) == 1 and OWN_KEY not in stored[0].ciphertext and stored[0].purpose == "image-generation-key"


async def test_the_key_can_be_replaced_and_forgotten(client):
    await configure(client, base_url="https://gateway.internal:4000/v1", api_key=OWN_KEY)
    become(ROOT, admin=True)

    replaced = await client.patch("/api/admin/image-generation", json={"api_key": "another-fake-key-fake-key"})
    forgotten = await client.patch(
        "/api/admin/image-generation", json={"clear_key": True, "base_url": None, "enabled": False}
    )

    assert replaced.json()["has_key"] is True and forgotten.json()["has_key"] is False
    async with async_session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(StoredSecret))).scalar_one() == 0


async def test_another_address_than_the_hubs_needs_its_own_key_so_the_hubs_never_goes_elsewhere(client):
    become(ROOT, admin=True)

    response = await client.patch(
        "/api/admin/image-generation", json={"base_url": "https://third-party.example.test/v1", "model": "m"}
    )

    assert response.status_code == 422 and response.json()["detail"]["code"] == "reglage_invalide"


async def test_the_function_cannot_be_turned_on_without_a_model(client):
    become(ROOT, admin=True)

    response = await client.patch("/api/admin/image-generation", json={"enabled": True})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"size": "huge"},
        {"quality": "ultra"},
        {"daily_limit": 0},
        {"max_image_bytes": 10},
        {"base_url": "ftp://x.example.test"},
        {"base_url": "https://user:pass@x.example.test/v1", "api_key": "k"},
    ],
)
async def test_settings_that_make_no_sense_are_refused(client, body):
    become(ROOT, admin=True)

    assert (await client.patch("/api/admin/image-generation", json=body)).status_code == 422


# --- a request: how the provider is called ---


async def test_a_request_calls_the_hub_with_no_response_format_and_the_settings_asked(client, provider):
    await configure(client, size="1536x1024", quality="high")

    response = await generate(client, "  un chat sur un toit  ")

    assert response.status_code == 200, response.text
    [call] = provider.calls
    assert call["base_url"] == HUB_URL and call["api_key"] == HUB_KEY
    assert call["model"] == "img-1" and call["prompt"] == "un chat sur un toit" and call["n"] == 1
    assert call["size"] == "1536x1024" and call["quality"] == "high"
    assert "response_format" not in call


async def test_another_address_is_called_with_its_own_key(client, provider):
    await configure(client, base_url="https://gateway.internal:4000/v1", api_key=OWN_KEY)

    await generate(client)

    assert (
        provider.calls[0]["base_url"] == "https://gateway.internal:4000/v1" and provider.calls[0]["api_key"] == OWN_KEY
    )
    assert HUB_KEY not in str(provider.calls)


async def test_a_base64_answer_makes_an_image_in_a_new_conversation_that_stays_after_a_reload(client, provider, bucket):
    await configure(client)

    response = await generate(client, "un chat sur un toit")
    body = response.json()
    conversation_id = body["conversation_id"]
    reloaded = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()

    [image] = body["message"]["images"]
    assert image["ai_generated"] is True and (image["width"], image["height"]) == (8, 6) and image["model"] == "img-1"
    assert body["user_message"]["content"] == "un chat sur un toit" and body["message"]["role"] == "assistant"
    assert [message["role"] for message in reloaded] == ["user", "assistant"]
    assert reloaded[1]["images"][0]["id"] == image["id"] and reloaded[0]["images"] == []
    assert "un chat sur un toit" in reloaded[1]["content"]
    titles = [c["title"] for c in (await client.get("/api/conversations")).json()["items"]]
    assert titles == ["un chat sur un toit"]
    [(key, (stored, content_type))] = bucket.items()
    assert key == f"images/{conversation_id}/{image['id']}.png" and content_type == "image/png"


async def test_the_image_is_served_to_its_owner_with_the_type_that_was_checked(client, provider):
    await configure(client)
    body = (await generate(client)).json()
    image_id = body["message"]["images"][0]["id"]

    served = await client.get(f"/api/conversations/{body['conversation_id']}/images/{image_id}")

    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff" and "private" in served.headers["cache-control"]
    assert served.content.startswith(b"\x89PNG") and b"AI-generated image" in served.content  # labelled in the file


@pytest.mark.parametrize(("image", "content_type"), [(jpeg(), "image/jpeg"), (webp_lossless(), "image/webp")])
async def test_a_jpeg_and_a_webp_are_kept_and_served_as_what_they_are(client, provider, image, content_type):
    provider.image = image
    await configure(client)
    body = (await generate(client)).json()

    served = await client.get(
        f"/api/conversations/{body['conversation_id']}/images/{body['message']['images'][0]['id']}"
    )

    assert served.headers["content-type"] == content_type and served.content == image


async def test_a_request_in_an_existing_conversation_goes_after_what_is_there(client, provider):
    await configure(client)
    first = (await generate(client, "premier")).json()

    second = (await generate(client, "second", conversation_id=first["conversation_id"])).json()
    messages = (await client.get(f"/api/conversations/{first['conversation_id']}/messages")).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["premier", "second"]
    assert [len(m["images"]) for m in messages] == [0, 1, 0, 1]


async def test_a_conversation_that_is_not_theirs_is_not_found_and_nothing_is_called(client, provider):
    await configure(client)
    become(BOB)
    theirs = (await generate(client, "à Bob")).json()["conversation_id"]
    become(ALICE)
    calls = len(provider.calls)

    response = await generate(client, "dans la conversation de Bob", conversation_id=theirs)

    assert response.status_code == 404 and len(provider.calls) == calls


# --- the answer by address: fetched by the server, and never trusted ---


async def test_an_answer_by_address_is_fetched_by_the_server_and_stored_by_muffin(client, provider, downloads, bucket):
    provider.url = PUBLIC_IMAGE
    await configure(client)

    body = (await generate(client)).json()

    [request] = downloads.requests
    assert str(request.url) == PUBLIC_IMAGE
    [image] = body["message"]["images"]
    assert (image["width"], image["height"]) == (4, 4) and PUBLIC_IMAGE not in str(body)
    served = await client.get(f"/api/conversations/{body['conversation_id']}/images/{image['id']}")
    assert served.status_code == 200 and served.content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "address",
    [
        "http://93.184.216.34/cat.png",  # not https
        "https://10.0.0.5/cat.png",  # the internal network
        "https://169.254.169.254/latest/meta-data",  # the cloud's metadata
        "https://127.0.0.1/cat.png",
        "https://user:secret@93.184.216.34/cat.png",
        "file:///etc/passwd",
    ],
)
async def test_an_address_that_is_not_public_https_is_never_fetched(client, provider, downloads, address):
    provider.url = address
    await configure(client)

    response = await generate(client)

    assert response.status_code == 502 and response.json()["detail"]["code"] == "image_invalide"
    assert downloads.requests == []
    assert (await client.get("/api/conversations")).json()["items"] == []


async def test_a_redirect_is_not_followed(client, provider, downloads):
    provider.url = PUBLIC_IMAGE
    downloads.status = 302
    downloads.headers = {"location": "https://10.0.0.5/secret"}
    await configure(client)

    response = await generate(client)

    assert response.status_code == 502 and len(downloads.requests) == 1


async def test_an_image_by_address_that_is_too_heavy_is_refused_before_and_while_it_is_read(
    client, provider, downloads
):
    provider.url = PUBLIC_IMAGE
    await configure(client, max_image_bytes=100 * 1024)
    downloads.headers = {"content-length": str(5 * 1024 * 1024)}
    declared = await generate(client)
    downloads.headers = {}
    downloads.body = png(4, 4) + b"\x00" * (200 * 1024)
    streamed = await generate(client)

    assert declared.json()["detail"]["code"] == "image_trop_lourde"
    assert streamed.json()["detail"]["code"] == "image_trop_lourde"


# --- the bytes are checked ---


@pytest.mark.parametrize(
    "content",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<html><script>alert(1)</script></html>",
        b"GIF89a\x01\x00\x01\x00",
        b"not an image at all",
    ],
)
async def test_what_is_not_a_raster_image_is_refused_and_nothing_is_kept(client, provider, bucket, content):
    provider.image = content
    await configure(client)

    response = await generate(client)

    assert response.status_code == 502 and response.json()["detail"]["code"] == "image_invalide"
    assert bucket == {} and (await client.get("/api/conversations")).json()["items"] == []


async def test_an_image_that_is_too_heavy_or_too_large_is_refused(client, provider, bucket, monkeypatch):
    await configure(client, max_image_bytes=100 * 1024)
    provider.image = png(8, 6) + b"\x00" * (200 * 1024)
    heavy = await generate(client)
    provider.image = png(10000, 10)
    large = await generate(client)

    assert heavy.json()["detail"]["code"] == "image_trop_lourde"
    assert large.json()["detail"]["code"] == "image_invalide" and bucket == {}


async def test_an_answer_with_no_image_is_refused(client, provider):
    await configure(client)
    provider.image = b""

    response = await generate(client)

    assert response.status_code == 502


# --- who may, and how many ---


async def test_a_prompt_that_is_empty_or_too_long_is_refused_and_nothing_is_called(client, provider, monkeypatch):
    monkeypatch.setattr(image_generation_service._settings, "IMAGES_PROMPT_MAX_CHARS", 50)
    await configure(client)

    empty = await generate(client, "   ")
    long = await generate(client, "x" * 51)

    assert empty.json()["detail"]["code"] == "invite_vide" and long.json()["detail"]["code"] == "invite_trop_longue"
    assert provider.calls == []


async def test_only_the_groups_allowed_may_generate_and_an_administrator_always_may(client, provider):
    await configure(client, allowed_groups=["communication"])

    become(ALICE, ["rh"])
    outside = await generate(client)
    outside_status = (await client.get("/api/images/status")).json()
    become(BOB, ["communication"])
    inside = await generate(client)
    inside_status = (await client.get("/api/images/status")).json()
    become(ROOT, [], admin=True)
    admin = await generate(client)

    assert outside.status_code == 403 and outside.json()["detail"]["code"] == "non_autorise"
    assert outside_status["available"] is False and inside_status["available"] is True
    assert inside.status_code == 200 and admin.status_code == 200 and len(provider.calls) == 2


async def test_the_day_is_limited_and_a_refused_request_calls_nothing(client, provider):
    await configure(client, daily_limit=2)

    results = [await generate(client, f"image {n}") for n in range(3)]
    remaining = (await client.get("/api/images/status")).json()["remaining_today"]

    assert [r.status_code for r in results] == [200, 200, 429]
    assert results[2].json()["detail"]["code"] == "quota_depasse" and len(provider.calls) == 2
    assert remaining == 0
    become(BOB)  # the quota is each person's own
    assert (await generate(client, "pour Bob")).status_code == 200


async def test_the_rate_of_a_person_is_limited_and_nothing_is_called_past_it(client, provider, monkeypatch):
    monkeypatch.setattr(image_generation_service._settings, "IMAGES_PER_USER_PER_MINUTE", 2)
    await configure(client)

    results = [await generate(client, f"image {n}") for n in range(3)]

    assert [r.status_code for r in results] == [200, 200, 429]
    assert results[2].json()["detail"]["code"] == "trop_de_demandes" and len(provider.calls) == 2


async def test_a_request_that_gave_no_image_does_not_count_against_the_day(client, provider):
    await configure(client, daily_limit=1)
    provider.error = status_error(NotFoundError, 404)

    failed = await generate(client)
    provider.error = None
    worked = await generate(client)

    assert failed.status_code == 502 and worked.status_code == 200


async def test_a_quota_that_cannot_be_checked_stops_the_request_before_the_provider(client, provider, monkeypatch):
    await configure(client)

    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(image_generation_service, "async_redis", broken)
    response = await generate(client)

    assert response.status_code == 503 and response.json()["detail"]["code"] == "quota_indisponible"
    assert provider.calls == []


# --- when the provider fails: a code, and nothing of what it said ---


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (status_error(AuthenticationError, 401, "invalid_api_key"), 502, "cle_refusee"),
        (status_error(NotFoundError, 404, "model_not_found"), 502, "modele_introuvable"),
        (status_error(BadRequestError, 400, "unknown_parameter"), 502, "parametre_refuse"),
        (status_error(BadRequestError, 400, "content_policy_violation"), 422, "refus_politique"),
        (status_error(BadRequestError, 400, "moderation_blocked"), 422, "refus_politique"),
        (status_error(RateLimitError, 429, "rate_limit_exceeded"), 503, "fournisseur_surcharge"),
        (APITimeoutError(request=REQUEST), 504, "delai_depasse"),
        (APIConnectionError(request=REQUEST), 502, "fournisseur_injoignable"),
        (RuntimeError("PROVIDER-TEXT-THAT-MUST-NOT-LEAK"), 502, "fournisseur_en_erreur"),
    ],
)
async def test_the_failures_of_the_provider_are_told_by_a_code_and_never_by_its_words(
    client, provider, error, status, code
):
    await configure(client, base_url="https://gateway.internal:4000/v1", api_key=OWN_KEY)
    provider.error = error

    response = await generate(client)

    assert (response.status_code, response.json()["detail"]["code"]) == (status, code)
    assert "PROVIDER-TEXT" not in response.text and OWN_KEY not in response.text and HUB_KEY not in response.text
    assert (await client.get("/api/conversations")).json()["items"] == []


# --- what is theirs ---


async def test_an_image_is_read_by_its_owner_only(client, provider):
    await configure(client)
    body = (await generate(client)).json()
    image_id = body["message"]["images"][0]["id"]
    url = f"/api/conversations/{body['conversation_id']}/images/{image_id}"

    become(BOB)
    stranger = await client.get(url)
    strangers_messages = await client.get(f"/api/conversations/{body['conversation_id']}/messages")
    become(ALICE)
    other_conversation = await client.get(f"/api/conversations/{uuid.uuid4()}/images/{image_id}")

    assert stranger.status_code == 404 and strangers_messages.status_code == 404
    assert other_conversation.status_code == 404


async def test_an_image_goes_with_its_conversation_and_its_file_with_it(client, provider, bucket):
    await configure(client)
    body = (await generate(client)).json()
    assert len(bucket) == 1

    deleted = await client.delete(f"/api/conversations/{body['conversation_id']}")

    assert deleted.status_code == 204 and bucket == {}
    async with async_session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(MessageImage))).scalar_one() == 0


# --- what it costs ---


async def test_an_image_is_recorded_in_the_usage_by_step_with_its_count_and_its_size(client, provider):
    await configure(client)
    await generate(client)
    await generate(client, "une autre")

    async with async_session_factory() as session:
        rows = (await session.execute(select(TokenUsage).where(TokenUsage.step == "image_generation"))).scalars().all()

    assert (
        len(rows) == 2
        and {row.kind for row in rows} == {TokenUsageKind.IMAGE}
        and {row.user_id for row in rows} == {ALICE}
    )
    assert {(row.images, row.pixels, row.total_tokens, row.model) for row in rows} == {(1, 48, 0, "img-1")}


async def test_the_failed_request_is_not_recorded(client, provider):
    await configure(client)
    provider.error = status_error(AuthenticationError, 401, "invalid_api_key")

    await generate(client)

    async with async_session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(TokenUsage).where(TokenUsage.step == "image_generation")
            )
        ).scalar_one()
    assert count == 0


# --- the administrator's test ---


async def test_the_test_makes_a_small_image_and_says_how_long_it_took_without_keeping_it(client, provider, bucket):
    await configure(client)
    become(ROOT, admin=True)

    result = (await client.post("/api/admin/image-generation/test")).json()

    assert result["ok"] is True and result["response_format"] == "b64_json" and result["duration_ms"] >= 0
    assert (result["width"], result["height"], result["content_type"]) == (8, 6, "image/png")
    assert result["image"].startswith("data:image/png;base64,")
    assert bucket == {} and len(provider.calls) == 1
    assert (await client.get("/api/conversations")).json()["items"] == []
    async with async_session_factory() as session:
        assert (
            await session.execute(
                select(func.count()).select_from(TokenUsage).where(TokenUsage.step == "image_generation")
            )
        ).scalar_one() == 0


async def test_the_test_works_before_the_function_is_turned_on_and_counts_against_no_quota(client, provider):
    become(ROOT, admin=True)
    await client.patch("/api/admin/image-generation", json={"model": "img-1", "daily_limit": 1})
    for _ in range(3):
        assert (await client.post("/api/admin/image-generation/test")).json()["ok"] is True

    assert len(provider.calls) == 3 and (await client.get("/api/images/status")).json()["available"] is False


async def test_the_test_says_a_url_answer_and_what_went_wrong_with_a_code_for_the_administrator(
    client, provider, downloads
):
    await configure(client)
    become(ROOT, admin=True)
    provider.url = PUBLIC_IMAGE
    by_address = (await client.post("/api/admin/image-generation/test")).json()
    provider.url = None
    provider.error = status_error(AuthenticationError, 401, "invalid_api_key")
    refused = (await client.post("/api/admin/image-generation/test")).json()
    provider.error = status_error(NotFoundError, 404)
    unknown = (await client.post("/api/admin/image-generation/test")).json()

    assert by_address["ok"] is True and by_address["response_format"] == "url"
    assert (refused["ok"], refused["code"]) == (False, "cle_refusee") and "401" in refused["message"]
    assert (unknown["ok"], unknown["code"]) == (False, "modele_introuvable") and "404" in unknown["message"]
    assert "PROVIDER-TEXT" not in str(refused) + str(unknown)


async def test_the_test_of_a_function_not_configured_says_so(client):
    become(ROOT, admin=True)

    result = (await client.post("/api/admin/image-generation/test")).json()

    assert result["ok"] is False and result["code"] == "non_configuree"


async def test_the_usage_of_a_person_counts_their_images_and_pixels_by_step(client, provider):
    await configure(client)
    await generate(client)
    await generate(client, "une autre")

    mine = (await client.get("/api/usage/me")).json()

    assert (mine["totals"]["images"], mine["totals"]["pixels"], mine["totals"]["total_tokens"]) == (2, 96, 0)
    [step] = [step for step in mine["by_step"] if step["step"] == "image_generation"]
    assert (step["images"], step["pixels"], step["calls"]) == (2, 96, 2)


async def test_an_image_is_made_even_when_its_usage_cannot_be_written(client, provider, monkeypatch):
    async def broken(self, usage):
        raise RuntimeError("the database refused the usage")

    monkeypatch.setattr(TokenUsageRepository, "add", broken)
    await configure(client)

    response = await generate(client)

    assert response.status_code == 200 and len(response.json()["message"]["images"]) == 1
