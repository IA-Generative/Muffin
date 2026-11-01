import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GuardrailSettings
from app.core import url_guard
from app.core.security.factory import RequestContext
from app.guardrails import http as http_guardrail
from app.guardrails import runner
from app.guardrails.presets import PRESETS
from app.guardrails.rules import InvalidRulesError, compile_config
from app.guardrails.types import (
    OUTCOME_BLOCK,
    OUTCOME_CONTINUE,
    OUTCOME_REDACTION,
    OUTCOME_WARNING,
    Decision,
    Policy,
    Result,
    Spec,
)
from app.models.guardrail import Enforcement, Guardrail, GuardrailAudit, GuardrailPolicy, GuardrailResult, GuardrailType
from app.models.message import Message
from app.repositories.guardrail_repository import GuardrailRepository
from app.repositories.run_repository import RunRepository
from app.schemas.guardrail import (
    AuditOut,
    GuardrailCreate,
    GuardrailOut,
    GuardrailStatOut,
    GuardrailStatsOut,
    GuardrailUpdate,
    PolicyOut,
    PolicyUpdate,
    ProbeOut,
    ProbeVerdictOut,
    RunGuardrailOut,
)
from app.services.secret_store_service import SecretNotFoundError, SecretStore

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = GuardrailSettings()

_PURPOSE = "guardrail-http-key"
# What a model reads in the place of a message the guardrails stopped, in the turns that follow.
BLOCKED_PLACEHOLDER = "[Message écarté : il ne respectait pas la politique d'usage de l'application.]"


class GuardrailError(Exception):
    """A request that is refused, said with a code that does not change and words for the administrator. `status` is
    the HTTP status the API answers with."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class GuardrailNotFoundError(Exception):
    pass


def text_for_models(message: Message) -> str:
    """What a model may read of a message of the conversation (#516): the text as it was masked, or a placeholder for a
    message that was stopped. Never the original of either."""
    if message.guardrail_action == "blocked" and message.role.value == "user":
        return BLOCKED_PLACEHOLDER
    return message.redacted_content or message.content


def _display(user: RequestContext) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email or user.user_id


def applies(guardrail: Guardrail, groups: list[str], assistant_id: uuid.UUID | None) -> bool:
    """Whether a guardrail is for this request: for everyone when it has no scope, else for the groups and the
    assistants it names."""
    if not guardrail.scope_groups and not guardrail.scope_assistants:
        return True
    if set(guardrail.scope_groups) & set(groups):
        return True
    return assistant_id is not None and str(assistant_id) in guardrail.scope_assistants


def _snapshot(guardrail: Guardrail) -> dict[str, Any]:
    """What the audit keeps of a guardrail: all of its settings, and that there is a key - never the key."""
    return {
        "name": guardrail.name,
        "description": guardrail.description,
        "type": guardrail.type.value,
        "config": guardrail.config,
        "enabled": guardrail.enabled,
        "enforcement": guardrail.enforcement.value,
        "stage": guardrail.stage,
        "timeout_ms": guardrail.timeout_ms,
        "on_error": guardrail.on_error.value,
        "critical": guardrail.critical,
        "scope_groups": guardrail.scope_groups,
        "scope_assistants": guardrail.scope_assistants,
        "refusal_message": guardrail.refusal_message,
        "category_label": guardrail.category_label,
        "has_key": guardrail.secret_id is not None,
        "version": guardrail.version,
    }


def present(guardrail: Guardrail) -> GuardrailOut:
    return GuardrailOut(
        id=guardrail.id,
        name=guardrail.name,
        description=guardrail.description,
        type=guardrail.type,
        config=guardrail.config,
        enabled=guardrail.enabled,
        enforcement=guardrail.enforcement,
        stage=guardrail.stage,
        timeout_ms=guardrail.timeout_ms,
        on_error=guardrail.on_error,
        critical=guardrail.critical,
        scope_groups=list(guardrail.scope_groups),
        scope_assistants=list(guardrail.scope_assistants),
        refusal_message=guardrail.refusal_message,
        category_label=guardrail.category_label,
        has_key=guardrail.secret_id is not None,
        preset_key=guardrail.preset_key,
        position=guardrail.position,
        version=guardrail.version,
        updated_by=guardrail.updated_by,
        updated_at=guardrail.updated_at,
    )


def present_policy(policy: GuardrailPolicy) -> PolicyOut:
    return PolicyOut.model_validate(policy, from_attributes=True)


def policy_of(row: GuardrailPolicy) -> Policy:
    return Policy(
        aggregation=row.aggregation,
        quorum=row.quorum,
        wait_strategy=row.wait_strategy,
        timeout_ms=row.timeout_ms,
        on_incomplete=row.on_incomplete,
        min_verdicts=row.min_verdicts,
        show_category=row.show_category,
        default_refusal=row.default_refusal,
    )


class GuardrailService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.guardrails = GuardrailRepository(db)

    # --- what runs on a request ---

    async def _spec(self, guardrail: Guardrail) -> Spec:
        secret = None
        if guardrail.secret_id is not None:
            try:
                secret = await SecretStore(self.db).reveal(guardrail.secret_id, owner=None, purpose=_PURPOSE)
            except SecretNotFoundError:
                logger.warning(f"The key of the guardrail {guardrail.name} is gone")
        return Spec(
            id=guardrail.id,
            name=guardrail.name,
            type=guardrail.type,
            config=guardrail.config,
            enforcement=guardrail.enforcement,
            stage=guardrail.stage,
            timeout_ms=guardrail.timeout_ms,
            on_error=guardrail.on_error,
            critical=guardrail.critical,
            version=guardrail.version,
            refusal_message=guardrail.refusal_message,
            category_label=guardrail.category_label,
            secret=secret,
        )

    async def evaluate_run(self, run_id: uuid.UUID) -> RunGuardrailOut | None:
        """What the guardrails decide for the request of a run, recorded on the run and on its message. Made once: a run
        asked again - a delivery that came twice - gets what was decided. The text is read from the message, which is
        the person's own, never from what the run holds, which may be masked. None when the run is unknown."""
        run = await RunRepository(self.db).get_by_id(run_id)
        if run is None:
            return None
        if await self.guardrails.has_results(run.id):
            outcome = {"blocked": OUTCOME_BLOCK, "redacted": OUTCOME_REDACTION, "warned": OUTCOME_WARNING}.get(
                run.guardrail_outcome or "", OUTCOME_CONTINUE
            )
            return RunGuardrailOut(outcome=outcome, query=run.query, message=run.guardrail_notice, checked=0, flagged=0)
        enabled = [
            guardrail
            for guardrail in await self.guardrails.list_enabled()
            if applies(guardrail, list(run.user_groups or []), run.assistant_id)
        ]
        if not enabled:
            return RunGuardrailOut(outcome=OUTCOME_CONTINUE, query=run.query, message=None, checked=0, flagged=0)
        message = await self.db.get(Message, run.message_id)
        text = message.content if message is not None else run.query
        policy = policy_of(await self.guardrails.policy())
        decision = await runner.evaluate(
            text,
            [await self._spec(guardrail) for guardrail in enabled],
            policy,
            user_id=run.user_id,
            run_id=str(run.id),
        )
        await self._record(run.id, run.message_id, decision)
        self._apply(run, message, decision)
        await self.db.commit()
        return RunGuardrailOut(
            outcome=decision.outcome,
            query=run.query,
            message=decision.message,
            checked=len(decision.results),
            flagged=sum(1 for result in decision.results if result.flagged),
        )

    async def _record(self, run_id: uuid.UUID, message_id: uuid.UUID | None, decision: Decision) -> None:
        """The verdicts, with no text: the guardrail and its version, the verdict, the category, the score, the time."""
        await self.guardrails.add_results(
            [
                GuardrailResult(
                    run_id=run_id,
                    message_id=message_id,
                    guardrail_id=result.spec.id,
                    guardrail_name=result.spec.name,
                    guardrail_version=result.spec.version,
                    stage=result.spec.stage,
                    enforcement=result.spec.enforcement.value,
                    verdict=result.verdict.status,
                    category=result.verdict.category,
                    score=result.verdict.score,
                    latency_ms=result.verdict.latency_ms,
                    action=result.action,
                )
                for result in decision.results
            ]
        )

    @staticmethod
    def _apply(run, message: Message | None, decision: Decision) -> None:  # noqa: ANN001
        if decision.outcome == OUTCOME_CONTINUE:
            return
        run.guardrail_notice = decision.message
        if decision.outcome == OUTCOME_BLOCK:
            run.guardrail_outcome, action = "blocked", "blocked"
        elif decision.outcome == OUTCOME_REDACTION:
            run.guardrail_outcome, action = "redacted", "redacted"
            # What the models read of this request, everywhere the run reads it (the tools, the editing...): the
            # message keeps what the person wrote.
            run.query = decision.text
        else:
            run.guardrail_outcome, action = "warned", "warned"
        if message is not None:
            message.guardrail_action = action
            if decision.outcome == OUTCOME_REDACTION:
                message.redacted_content = decision.text

    async def screen_text(self, user: RequestContext, text: str, assistant_id: uuid.UUID | None = None) -> Decision:
        """What the guardrails would decide for a text that is not a message of the chat yet - the question of a routine
        (#524), checked when it is written as it will be at each run. Nothing is recorded and no run is made."""
        specs = [
            await self._spec(guardrail)
            for guardrail in await self.guardrails.list_enabled()
            if applies(guardrail, list(user.groups), assistant_id)
        ]
        policy = policy_of(await self.guardrails.policy())
        return await runner.evaluate(text, specs, policy, user_id=user.user_id)

    async def screen_history(self, user: RequestContext, messages: list[Message]) -> None:
        """The earlier messages a client of the OpenAI-compatible API sends along with its question (#516): they become
        the conversation the agent reads, and no run checks them. They go through the guardrails of type `rules` - free,
        and which run before anything - so that the history is no way round them. The guardrails that call a model or a
        service are for the question of the run, as they are for every message of the chat: what they would cost for
        each message of a long history is not worth what it would add. Nothing is recorded here."""
        specs = [
            await self._spec(guardrail)
            for guardrail in await self.guardrails.list_enabled()
            if guardrail.type == GuardrailType.RULES and applies(guardrail, list(user.groups), None)
        ]
        if not specs:
            return
        policy = policy_of(await self.guardrails.policy())
        for message in messages:
            if message.role.value != "user":
                continue
            decision = await runner.evaluate(message.content, specs, policy, user_id=user.user_id)
            if decision.outcome == OUTCOME_BLOCK:
                message.guardrail_action = "blocked"
            elif decision.outcome == OUTCOME_REDACTION:
                message.guardrail_action, message.redacted_content = "redacted", decision.text
        await self.db.flush()

    # --- the guardrails, for an administrator ---

    async def ensure_presets(self) -> None:
        """Makes the guardrails that come with the application, once: an administrator who deletes one does not see it
        come back."""
        policy = await self.guardrails.policy()
        if policy.presets_made:
            return
        for preset in PRESETS:
            if await self.guardrails.get_by_name(preset["name"]) is None:
                await self.guardrails.add(
                    Guardrail(**preset, enabled=False, position=await self.guardrails.next_position())
                )
        policy.presets_made = True
        await self.db.commit()

    async def all(self) -> list[GuardrailOut]:
        await self.ensure_presets()
        return [present(guardrail) for guardrail in await self.guardrails.list_all()]

    async def get(self, guardrail_id: uuid.UUID) -> GuardrailOut:
        return present(await self._get(guardrail_id))

    async def create(self, user: RequestContext, body: GuardrailCreate) -> GuardrailOut:
        if await self.guardrails.count() >= _settings.GUARDRAILS_MAX:
            raise GuardrailError("trop_de_garde_fous", f"Au plus {_settings.GUARDRAILS_MAX} garde-fous.", 409)
        if await self.guardrails.get_by_name(body.name.strip()) is not None:
            raise GuardrailError("nom_deja_pris", "Un garde-fou porte déjà ce nom.", 409)
        config = await self._valid(body.type, body.config, body.enforcement)
        guardrail = await self.guardrails.add(
            Guardrail(
                name=body.name.strip(),
                description=body.description.strip(),
                type=body.type,
                config=config,
                enabled=body.enabled,
                enforcement=body.enforcement,
                stage=body.stage,
                timeout_ms=body.timeout_ms,
                on_error=body.on_error,
                critical=body.critical,
                scope_groups=[group.strip() for group in body.scope_groups if group.strip()],
                scope_assistants=[str(item) for item in body.scope_assistants],
                refusal_message=(body.refusal_message or "").strip() or None,
                category_label=(body.category_label or "").strip() or None,
                position=await self.guardrails.next_position(),
                updated_by=user.user_id,
            )
        )
        if body.api_key:
            await self._set_key(guardrail, body.api_key, user)
        await self._audit(user, "created", guardrail, None, _snapshot(guardrail))
        await self.db.commit()
        await self.db.refresh(guardrail)
        logger.info(f"Guardrail {guardrail.name} created by {user.user_id}")
        return present(guardrail)

    async def update(self, user: RequestContext, guardrail_id: uuid.UUID, body: GuardrailUpdate) -> GuardrailOut:
        guardrail = await self._get(guardrail_id)
        before = _snapshot(guardrail)
        if body.name is not None and body.name.strip() != guardrail.name:
            if await self.guardrails.get_by_name(body.name.strip()) is not None:
                raise GuardrailError("nom_deja_pris", "Un garde-fou porte déjà ce nom.", 409)
            guardrail.name = body.name.strip()
        if body.description is not None:
            guardrail.description = body.description.strip()
        enforcement = body.enforcement or guardrail.enforcement
        config = body.config if body.config is not None else guardrail.config
        guardrail.config = await self._valid(guardrail.type, config, enforcement)
        guardrail.enforcement = enforcement
        for field in ("enabled", "stage", "timeout_ms", "on_error", "critical"):
            value = getattr(body, field)
            if value is not None:
                setattr(guardrail, field, value)
        if body.scope_groups is not None:
            guardrail.scope_groups = [group.strip() for group in body.scope_groups if group.strip()]
        if body.scope_assistants is not None:
            guardrail.scope_assistants = [str(item) for item in body.scope_assistants]
        if body.clear_refusal_message:
            guardrail.refusal_message = None
        elif body.refusal_message is not None:
            guardrail.refusal_message = body.refusal_message.strip() or None
        if body.clear_category_label:
            guardrail.category_label = None
        elif body.category_label is not None:
            guardrail.category_label = body.category_label.strip() or None
        if body.clear_key:
            await self._forget_key(guardrail)
        elif body.api_key:
            await self._set_key(guardrail, body.api_key, user)
        after = _snapshot(guardrail)
        if after != before:
            guardrail.version += 1
            guardrail.updated_by = user.user_id
            after["version"] = guardrail.version
            await self._audit(user, "updated", guardrail, before, after)
        await self.db.commit()
        await self.db.refresh(guardrail)
        return present(guardrail)

    async def delete(self, user: RequestContext, guardrail_id: uuid.UUID) -> None:
        guardrail = await self._get(guardrail_id)
        before = _snapshot(guardrail)
        await self._forget_key(guardrail)
        await self._audit(user, "deleted", guardrail, before, None)
        await self.guardrails.delete(guardrail)
        await self.db.commit()
        logger.info(f"Guardrail {before['name']} deleted by {user.user_id}")

    async def reorder(self, user: RequestContext, ids: list[uuid.UUID]) -> list[GuardrailOut]:
        guardrails = {guardrail.id: guardrail for guardrail in await self.guardrails.list_all()}
        if set(ids) != set(guardrails) or len(ids) != len(guardrails):
            raise GuardrailError("ordre_invalide", "L'ordre doit nommer chaque garde-fou une fois.")
        before = {str(item.id): item.position for item in guardrails.values()}
        for position, guardrail_id in enumerate(ids, start=1):
            guardrails[guardrail_id].position = position
        await self.guardrails.add_audit(
            GuardrailAudit(
                action="reordered",
                user_id=user.user_id,
                user_display=_display(user),
                before=before,
                after={str(guardrail_id): position for position, guardrail_id in enumerate(ids, start=1)},
            )
        )
        await self.db.commit()
        return [present(guardrail) for guardrail in await self.guardrails.list_all()]

    # --- the policy ---

    async def policy(self) -> PolicyOut:
        policy = await self.guardrails.policy()
        await self.db.commit()
        return present_policy(policy)

    async def update_policy(self, user: RequestContext, body: PolicyUpdate) -> PolicyOut:
        policy = await self.guardrails.policy()
        before = present_policy(policy).model_dump(mode="json", exclude={"updated_at"})
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(policy, field, value)
        policy.updated_by = user.user_id
        after = PolicyOut.model_validate(policy, from_attributes=True).model_dump(mode="json", exclude={"updated_at"})
        if after != before:
            await self.guardrails.add_audit(
                GuardrailAudit(
                    action="policy",
                    user_id=user.user_id,
                    user_display=_display(user),
                    before=before,
                    after=after,
                )
            )
        await self.db.commit()
        await self.db.refresh(policy)
        return present_policy(policy)

    # --- trying a text, the audit, the figures ---

    async def probe(self, user: RequestContext, text: str, guardrail_ids: list[uuid.UUID]) -> ProbeOut:
        """What each guardrail says of a text an administrator typed, and what the policy would do with the enabled
        ones. No run is made and nothing is recorded: the text is gone when the answer is sent."""
        chosen = [
            guardrail
            for guardrail in await self.guardrails.list_all()
            if not guardrail_ids or guardrail.id in guardrail_ids
        ]
        policy = policy_of(await self.guardrails.policy())
        specs = {guardrail.id: await self._spec(guardrail) for guardrail in chosen}
        enabled = [specs[guardrail.id] for guardrail in chosen if guardrail.enabled]
        decision = await runner.evaluate(text, enabled, policy, user_id=user.user_id)
        seen = {result.spec.id: result for result in decision.results}
        # A disabled guardrail is run on its own, to show what it would say. An enabled one that the decision did not
        # reach - a later stage, after a block - is not run: that is what would happen.
        alone = [specs[guardrail.id] for guardrail in chosen if not guardrail.enabled]
        verdicts_alone = await asyncio.gather(
            *(runner.run_one(spec, text, spec.timeout_ms / 1000, user_id=user.user_id) for spec in alone)
        )
        alone_by_id = {spec.id: verdict for spec, verdict in zip(alone, verdicts_alone, strict=True)}
        verdicts = []
        for guardrail in chosen:
            result: Result | None = seen.get(guardrail.id)
            verdict = result.verdict if result else alone_by_id.get(guardrail.id)
            verdicts.append(
                ProbeVerdictOut(
                    guardrail_id=guardrail.id,
                    name=guardrail.name,
                    enabled=guardrail.enabled,
                    stage=guardrail.stage,
                    enforcement=guardrail.enforcement,
                    verdict=verdict.status if verdict else "not_run",
                    category=verdict.category if verdict else None,
                    score=verdict.score if verdict else None,
                    latency_ms=verdict.latency_ms if verdict else 0,
                    action=result.action if result else "none",
                )
            )
        return ProbeOut(
            outcome=decision.outcome,
            message=decision.message,
            text=decision.text if decision.outcome != OUTCOME_BLOCK else "",
            incomplete=decision.incomplete,
            verdicts=verdicts,
        )

    async def audit(self, limit: int, offset: int, guardrail_id: uuid.UUID | None) -> tuple[list[AuditOut], int]:
        rows, total = await self.guardrails.audit(limit, offset, guardrail_id)
        return [AuditOut.model_validate(row, from_attributes=True) for row in rows], total

    async def stats(self, days: int) -> GuardrailStatsOut:
        since = datetime.now(UTC) - timedelta(days=days)
        checked, blocked = await self.guardrails.totals(since)
        return GuardrailStatsOut(
            days=days,
            requests_checked=checked,
            requests_blocked=blocked,
            rows=[
                GuardrailStatOut(
                    guardrail_id=row.guardrail_id,
                    name=row.guardrail_name,
                    day=row.day,
                    evaluated=row.evaluated,
                    flagged=row.flagged,
                    blocked=row.blocked,
                    failed=row.failed,
                    avg_latency_ms=round(float(row.avg_latency_ms), 1),
                    max_latency_ms=int(row.max_latency_ms),
                )
                for row in await self.guardrails.stats(since)
            ],
        )

    async def purge_results(self) -> int:
        removed = await self.guardrails.purge_results(
            datetime.now(UTC) - timedelta(days=_settings.GUARDRAILS_RESULTS_RETENTION_DAYS)
        )
        await self.db.commit()
        return removed

    # --- what is checked ---

    async def _get(self, guardrail_id: uuid.UUID) -> Guardrail:
        guardrail = await self.guardrails.get(guardrail_id)
        if guardrail is None:
            raise GuardrailNotFoundError(str(guardrail_id))
        return guardrail

    @staticmethod
    async def _valid(type_: GuardrailType, config: dict[str, Any], enforcement: Enforcement) -> dict[str, Any]:
        """The configuration of a type, checked: what an administrator must fix is said here, not on a request."""
        if enforcement == Enforcement.REDACT and type_ == GuardrailType.LLM:
            raise GuardrailError(
                "masquage_impossible",
                "Un garde-fou à base de modèle ne peut pas masquer : il ne sait pas où est le texte.",
            )
        if type_ == GuardrailType.RULES:
            try:
                compile_config(config)
            except InvalidRulesError as error:
                raise GuardrailError("regles_invalides", str(error)) from error
        elif type_ == GuardrailType.LLM:
            prompt = config.get("prompt")
            threshold = config.get("threshold", 0.5)
            categories = config.get("categories") or []
            if prompt is not None and (not isinstance(prompt, str) or len(prompt) > 4000):
                raise GuardrailError("prompt_invalide", "Les consignes du juge font 4000 caractères au plus.")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                raise GuardrailError("seuil_invalide", "Le seuil est un nombre de 0 à 1.")
            if (
                not isinstance(categories, list)
                or len(categories) > 20
                or any(not isinstance(item, str) or not item or len(item) > 64 for item in categories)
            ):
                raise GuardrailError("categories_invalides", "Au plus 20 catégories, de 64 caractères au plus.")
        else:
            try:
                await http_guardrail.check_address(str(config.get("url") or ""))
            except url_guard.UrlRefusedError as error:
                raise GuardrailError("adresse_refusee", str(error)) from error
        return config

    async def _set_key(self, guardrail: Guardrail, key: str, user: RequestContext) -> None:
        if guardrail.type != GuardrailType.HTTP:
            raise GuardrailError("cle_inutile", "Seul un garde-fou de type http a une clé.")
        store = SecretStore(self.db)
        if guardrail.secret_id is None:
            guardrail.secret_id = (
                await store.put(owner=None, purpose=_PURPOSE, plaintext=key, created_by=user.user_id)
            ).id
        else:
            await store.replace(guardrail.secret_id, key, owner=None, purpose=_PURPOSE)

    async def _forget_key(self, guardrail: Guardrail) -> None:
        if guardrail.secret_id is not None:
            try:
                await SecretStore(self.db).delete(guardrail.secret_id, owner=None, purpose=_PURPOSE)
            except SecretNotFoundError:
                pass
            guardrail.secret_id = None

    async def _audit(
        self, user: RequestContext, action: str, guardrail: Guardrail, before: dict | None, after: dict | None
    ) -> None:
        await self.guardrails.add_audit(
            GuardrailAudit(
                guardrail_id=guardrail.id,
                guardrail_name=guardrail.name,
                action=action,
                user_id=user.user_id,
                user_display=_display(user),
                before=before,
                after=after,
            )
        )
