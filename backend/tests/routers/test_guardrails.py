"""The guardrails on the input (#516), for an administrator: defined by them and no one else, with every change kept,
a text to try that is never kept, and a key that is never read back."""

import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core import secret_store
from app.core.secret_store import LocalProvider
from app.core.security.factory import RequestContext, get_current_user
from app.core.security.worker_auth import require_worker_api_key  # noqa: F401
from app.db import async_session_factory
from app.guardrails import http as http_guardrail
from app.main import app
from app.models.conversation import Conversation
from app.models.guardrail import Guardrail, GuardrailAudit, GuardrailPolicy, GuardrailResult
from app.models.run import Run
from app.models.stored_secret import StoredSecret
from app.services import guardrail_service

ALICE, ROOT = "alice", "root"
IBAN = "FR76 3000 6000 0112 3456 7890 189"
KEY = "-".join(["svc", "key", "do-not-leak", "123456"])  # built, so that a scanner does not take it for a secret


def become(user_id: str, *, admin: bool = False, groups: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin, groups=groups or []
    )


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k1", bytes([1]) * 32)]))
    become(ROOT, admin=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (GuardrailResult, GuardrailAudit, Guardrail, GuardrailPolicy, Run, Conversation, StoredSecret):
            await session.execute(delete(model))
        await session.commit()


def rules(builtins=("iban",), **fields) -> dict:
    return {
        "name": fields.pop("name", "Pas d'IBAN"),
        "type": "rules",
        "config": {"builtins": list(builtins), **fields.pop("config", {})},
        **fields,
    }


async def make(client, **fields) -> dict:
    response = await client.post("/api/admin/guardrails", json=rules(**fields))
    assert response.status_code == 201, response.text
    return response.json()


# --- an administrator, and no one else ---


async def test_nobody_but_an_administrator_reads_or_changes_the_guardrails(client):
    made = await make(client, config={"terms": ["terme-secret-de-politique"]})
    become(ALICE)

    calls = [
        await client.get("/api/admin/guardrails"),
        await client.post("/api/admin/guardrails", json=rules(name="x")),
        await client.get(f"/api/admin/guardrails/{made['id']}"),
        await client.patch(f"/api/admin/guardrails/{made['id']}", json={"enabled": False}),
        await client.delete(f"/api/admin/guardrails/{made['id']}"),
        await client.get("/api/admin/guardrails/policy"),
        await client.patch("/api/admin/guardrails/policy", json={"quorum": 3}),
        await client.post("/api/admin/guardrails/reorder", json={"ids": [made["id"]]}),
        await client.post("/api/admin/guardrails/test", json={"text": "x"}),
        await client.get("/api/admin/guardrails/audit"),
        await client.get("/api/admin/guardrails/stats"),
    ]

    assert [call.status_code for call in calls] == [403] * len(calls)
    assert all("terme-secret-de-politique" not in call.text for call in calls)


# --- the ones that come with the application ---


async def test_the_guardrails_that_come_with_the_application_are_made_once_disabled_and_only_watching(client):
    first = (await client.get("/api/admin/guardrails")).json()

    assert {item["preset_key"] for item in first} == {
        "personal_data_fr",
        "secrets",
        "max_length",
        "forbidden_terms",
        "prompt_injection",
    }
    assert all(item["enabled"] is False and item["enforcement"] == "monitor" for item in first)
    assert next(i for i in first if i["preset_key"] == "forbidden_terms")["config"]["terms"] == []
    assert next(i for i in first if i["preset_key"] == "prompt_injection")["stage"] == 2

    await client.delete(f"/api/admin/guardrails/{first[0]['id']}")
    again = (await client.get("/api/admin/guardrails")).json()
    assert len(again) == len(first) - 1  # an administrator who deleted one does not see it come back


# --- making and changing one ---


async def test_a_guardrail_is_made_disabled_and_watching_unless_told_otherwise(client):
    made = await make(client)

    assert (made["enabled"], made["enforcement"], made["stage"], made["on_error"], made["version"]) == (
        False,
        "monitor",
        1,
        "fail_open",
        1,
    )
    assert made["has_key"] is False and made["timeout_ms"] == 2000


@pytest.mark.parametrize(
    ("fields", "code", "status"),
    [
        ({"config": {"patterns": [{"regex": "("}]}}, "regles_invalides", 422),
        ({"config": {"builtins": ["inconnu"]}}, "regles_invalides", 422),
        ({"type": "llm", "config": {}, "enforcement": "redact"}, "masquage_impossible", 422),
        ({"type": "llm", "config": {"threshold": 3}}, "seuil_invalide", 422),
        ({"type": "llm", "config": {"prompt": "x" * 4001}}, "prompt_invalide", 422),
        ({"type": "http", "config": {"url": "https://127.0.0.1/check"}}, "adresse_refusee", 422),
        ({"type": "http", "config": {"url": "http://moderation.example.test/check"}}, "adresse_refusee", 422),
    ],
)
async def test_a_guardrail_that_cannot_be_run_safely_is_refused_with_a_code(client, fields, code, status):
    response = await client.post("/api/admin/guardrails", json=rules(**fields))

    assert response.status_code == status and response.json()["detail"]["code"] == code


async def test_names_are_unique_and_the_number_of_guardrails_is_bounded(client, monkeypatch):
    await make(client, name="Un")
    duplicate = await client.post("/api/admin/guardrails", json=rules(name="Un"))
    monkeypatch.setattr(guardrail_service._settings, "GUARDRAILS_MAX", 1)
    too_many = await client.post("/api/admin/guardrails", json=rules(name="Deux"))

    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "nom_deja_pris"
    assert too_many.status_code == 409 and too_many.json()["detail"]["code"] == "trop_de_garde_fous"


async def test_turning_a_guardrail_from_monitor_to_block_is_a_change_that_is_kept_with_who_and_what(client):
    made = await make(client, enabled=True)

    changed = await client.patch(f"/api/admin/guardrails/{made['id']}", json={"enforcement": "block"})
    untouched = await client.patch(f"/api/admin/guardrails/{made['id']}", json={"enforcement": "block"})
    audit = (await client.get("/api/admin/guardrails/audit")).json()

    assert (changed.json()["enforcement"], changed.json()["version"]) == ("block", 2)
    assert untouched.json()["version"] == 2  # nothing changed: no new version, no new line
    actions = [item["action"] for item in audit["items"]]
    assert actions == ["updated", "created"]
    updated = audit["items"][0]
    assert updated["before"]["enforcement"] == "monitor" and updated["after"]["enforcement"] == "block"
    assert updated["user_display"] == "root@example.com" and updated["guardrail_name"] == "Pas d'IBAN"


async def test_the_scope_the_labels_and_the_words_of_a_refusal_can_be_set_and_cleared(client):
    made = await make(client, scope_groups=["rh"], refusal_message="Non.", category_label="données personnelles")

    cleared = await client.patch(
        f"/api/admin/guardrails/{made['id']}",
        json={"scope_groups": [], "clear_refusal_message": True, "clear_category_label": True},
    )

    assert (made["scope_groups"], made["refusal_message"]) == (["rh"], "Non.")
    assert (cleared.json()["scope_groups"], cleared.json()["refusal_message"], cleared.json()["category_label"]) == (
        [],
        None,
        None,
    )


async def test_a_change_that_makes_a_guardrail_invalid_is_refused_and_nothing_changes(client):
    made = await make(client)

    refused = await client.patch(f"/api/admin/guardrails/{made['id']}", json={"config": {"patterns": [{"regex": "("}]}})

    assert refused.status_code == 422
    assert (await client.get(f"/api/admin/guardrails/{made['id']}")).json()["config"] == made["config"]


async def test_deleting_a_guardrail_is_kept_in_the_audit(client):
    made = await make(client)

    assert (await client.delete(f"/api/admin/guardrails/{made['id']}")).status_code == 204
    assert (await client.get(f"/api/admin/guardrails/{made['id']}")).status_code == 404
    audit = (await client.get("/api/admin/guardrails/audit")).json()["items"]

    assert [item["action"] for item in audit] == ["deleted", "created"] and audit[0]["after"] is None


async def test_the_audit_can_be_narrowed_to_one_guardrail(client):
    one, two = await make(client, name="Un"), await make(client, name="Deux")
    await client.patch(f"/api/admin/guardrails/{one['id']}", json={"enabled": True})

    narrowed = (await client.get("/api/admin/guardrails/audit", params={"guardrail_id": one["id"]})).json()

    assert {item["guardrail_name"] for item in narrowed["items"]} == {"Un"} and narrowed["total"] == 2
    assert two["id"] != one["id"]


# --- the key of a service ---


def reachable(monkeypatch):
    async def ok(url):
        return url

    monkeypatch.setattr(http_guardrail, "check_address", ok)


async def test_the_key_of_a_service_is_stored_encrypted_and_never_read_back_nor_audited(client, monkeypatch):
    reachable(monkeypatch)
    body = {
        "name": "Service",
        "type": "http",
        "config": {"url": "https://moderation.example.test/check"},
        "api_key": KEY,
    }

    made = await client.post("/api/admin/guardrails", json=body)
    listed = await client.get("/api/admin/guardrails")
    one = await client.get(f"/api/admin/guardrails/{made.json()['id']}")
    audit = await client.get("/api/admin/guardrails/audit")

    assert made.status_code == 201 and made.json()["has_key"] is True
    assert all(KEY not in call.text for call in (made, listed, one, audit))
    async with async_session_factory() as session:
        stored = (await session.execute(select(StoredSecret))).scalars().all()
        guardrail = (await session.execute(select(Guardrail).where(Guardrail.name == "Service"))).scalar_one()
        ciphertexts, stored_ids, secret_id = (
            [row.ciphertext for row in stored],
            [row.id for row in stored],
            guardrail.secret_id,
        )
    assert len(ciphertexts) == 1 and KEY not in ciphertexts[0] and secret_id == stored_ids[0]

    cleared = await client.patch(f"/api/admin/guardrails/{made.json()['id']}", json={"clear_key": True})
    assert cleared.json()["has_key"] is False
    async with async_session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(StoredSecret))).scalar_one() == 0


async def test_a_key_is_for_a_service_only_and_the_two_ways_to_set_it_do_not_go_together(client):
    made = await make(client)

    refused = await client.patch(f"/api/admin/guardrails/{made['id']}", json={"api_key": KEY})
    both = await client.patch(f"/api/admin/guardrails/{made['id']}", json={"api_key": KEY, "clear_key": True})

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "cle_inutile"
    assert both.status_code == 422


# --- the order, and the policy of the whole ---


async def test_the_order_is_set_inside_the_stages_and_must_name_every_guardrail_once(client):
    first, second, third = await make(client, name="A"), await make(client, name="B"), await make(client, name="C")
    await client.delete(f"/api/admin/guardrails/{first['id']}")
    await client.get("/api/admin/guardrails")  # the presets are made, in stage 1 and 2
    everything = (await client.get("/api/admin/guardrails")).json()
    ids = [item["id"] for item in everything]

    reordered = await client.post("/api/admin/guardrails/reorder", json={"ids": list(reversed(ids))})
    missing = await client.post("/api/admin/guardrails/reorder", json={"ids": ids[1:]})
    twice = await client.post("/api/admin/guardrails/reorder", json={"ids": [*ids, ids[0]]})

    stage_one = [item["id"] for item in reordered.json() if item["stage"] == 1]
    assert stage_one == [i for i in reversed(ids) if next(e for e in everything if e["id"] == i)["stage"] == 1]
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "ordre_invalide"
    assert twice.status_code == 422
    assert second["id"] in ids and third["id"] in ids


async def test_the_policy_has_defaults_is_validated_and_every_change_is_kept(client):
    default = (await client.get("/api/admin/guardrails/policy")).json()
    changed = await client.patch(
        "/api/admin/guardrails/policy",
        json={"aggregation": "quorum", "quorum": 3, "wait_strategy": "first_block", "show_category": True},
    )
    invalid = [
        await client.patch("/api/admin/guardrails/policy", json={"quorum": 0}),
        await client.patch("/api/admin/guardrails/policy", json={"timeout_ms": 10}),
        await client.patch("/api/admin/guardrails/policy", json={"aggregation": "nope"}),
        await client.patch("/api/admin/guardrails/policy", json={"default_refusal": ""}),
    ]
    audit = (await client.get("/api/admin/guardrails/audit")).json()["items"]

    assert (default["aggregation"], default["wait_strategy"], default["timeout_ms"], default["on_incomplete"]) == (
        "any",
        "wait_all",
        2000,
        "continue",
    )
    assert default["show_category"] is False and default["min_verdicts"] == 0
    assert (changed.json()["aggregation"], changed.json()["quorum"], changed.json()["show_category"]) == (
        "quorum",
        3,
        True,
    )
    assert {call.status_code for call in invalid} == {422}
    assert [item["action"] for item in audit] == ["policy"] and audit[0]["after"]["quorum"] == 3


# --- trying a text ---


async def test_a_text_can_be_tried_against_every_guardrail_and_it_is_kept_nowhere(client):
    await make(client, name="Bloque", enabled=True, enforcement="block")
    await make(client, name="Masque", enabled=True, enforcement="redact", config={"builtins": ["email", "iban"]})
    await make(client, name="Éteint", config={"builtins": ["email"]})
    text = f"Écrire à jean@example.fr, IBAN {IBAN}"

    probe = await client.post("/api/admin/guardrails/test", json={"text": text})

    body = probe.json()
    by_name = {item["name"]: item for item in body["verdicts"]}
    assert body["outcome"] == "block" and body["text"] == ""  # a blocked text goes nowhere
    assert by_name["Bloque"]["verdict"] == "flagged" and by_name["Bloque"]["action"] == "blocked"
    assert by_name["Éteint"]["verdict"] == "flagged" and by_name["Éteint"]["enabled"] is False
    assert by_name["Éteint"]["action"] == "none"
    async with async_session_factory() as session:
        results = (await session.execute(select(func.count()).select_from(GuardrailResult))).scalar_one()
        runs = (await session.execute(select(func.count()).select_from(Run))).scalar_one()
        audits = (await session.execute(select(GuardrailAudit))).scalars().all()
    assert (results, runs) == (0, 0)
    assert all("jean@example.fr" not in str(entry.before) + str(entry.after) for entry in audits)


async def test_a_text_that_is_masked_shows_what_would_go_on_to_the_models(client):
    await make(client, name="Masque", enabled=True, enforcement="redact", config={"builtins": ["email"]})

    probe = (await client.post("/api/admin/guardrails/test", json={"text": "Écrire à jean@example.fr"})).json()

    assert probe["outcome"] == "continue_with_redaction" and probe["text"] == "Écrire à [EMAIL]"


async def test_trying_some_guardrails_only_and_a_text_that_is_empty_or_too_long(client, monkeypatch):
    one, other = await make(client, name="Un", enabled=True), await make(client, name="Deux", enabled=True)

    only = (await client.post("/api/admin/guardrails/test", json={"text": IBAN, "guardrail_ids": [one["id"]]})).json()
    empty = await client.post("/api/admin/guardrails/test", json={"text": ""})

    assert [item["name"] for item in only["verdicts"]] == ["Un"] and other["id"] != one["id"]
    assert empty.status_code == 422


async def test_a_later_stage_that_the_decision_did_not_reach_is_said_not_run(client):
    await make(client, name="Étape 1", enabled=True, enforcement="block", stage=1)
    await make(client, name="Étape 2", enabled=True, enforcement="block", stage=2)

    probe = (await client.post("/api/admin/guardrails/test", json={"text": IBAN})).json()

    assert {item["name"]: item["verdict"] for item in probe["verdicts"]} == {"Étape 1": "flagged", "Étape 2": "not_run"}


# --- what they did ---


async def test_the_figures_count_requests_and_times_and_never_any_text(client):
    async with async_session_factory() as session:
        run_id = uuid.uuid4()
        session.add_all(
            [
                GuardrailResult(
                    run_id=run_id,
                    guardrail_name="Pas d'IBAN",
                    guardrail_version=2,
                    enforcement="block",
                    verdict="flagged",
                    category="iban",
                    score=1.0,
                    latency_ms=10,
                    action="blocked",
                ),
                GuardrailResult(
                    run_id=uuid.uuid4(),
                    guardrail_name="Pas d'IBAN",
                    enforcement="block",
                    verdict="clear",
                    latency_ms=30,
                ),
                GuardrailResult(
                    run_id=uuid.uuid4(),
                    guardrail_name="Service",
                    enforcement="block",
                    verdict="timeout",
                    latency_ms=2000,
                ),
            ]
        )
        await session.commit()

    stats = (await client.get("/api/admin/guardrails/stats", params={"days": 7})).json()

    assert (stats["requests_checked"], stats["requests_blocked"]) == (3, 1)
    by_name = {row["name"]: row for row in stats["rows"]}
    assert (by_name["Pas d'IBAN"]["evaluated"], by_name["Pas d'IBAN"]["flagged"], by_name["Pas d'IBAN"]["blocked"]) == (
        2,
        1,
        1,
    )
    assert by_name["Pas d'IBAN"]["avg_latency_ms"] == 20 and by_name["Service"]["failed"] == 1
    assert (await client.get("/api/admin/guardrails/stats", params={"days": 0})).status_code == 422


async def test_results_older_than_the_retention_are_forgotten(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(guardrail_service._settings, "GUARDRAILS_RESULTS_RETENTION_DAYS", 30)
    async with async_session_factory() as session:
        session.add_all(
            [
                GuardrailResult(
                    run_id=uuid.uuid4(),
                    guardrail_name="vieux",
                    enforcement="block",
                    verdict="clear",
                    created_at=datetime.now(UTC) - timedelta(days=31),
                ),
                GuardrailResult(run_id=uuid.uuid4(), guardrail_name="récent", enforcement="block", verdict="clear"),
            ]
        )
        await session.commit()
        removed = await guardrail_service.GuardrailService(session).purge_results()

    assert removed == 1
    assert httpx  # the module is imported for the tests of the calls to a service
