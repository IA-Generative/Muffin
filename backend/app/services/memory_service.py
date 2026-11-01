import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.memory import MemorySettings
from app.core.memory_rules import MemoryRefusedError, check, fold, key_of
from app.core.security.factory import RequestContext
from app.models.run import Run
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory
from app.repositories.memory_repository import MemoryRepository
from app.repositories.run_repository import RunRepository
from app.schemas.memory import (
    MemoryExportOut,
    MemoryItemOut,
    MemoryOut,
    MemoryStatsOut,
    RunMemoryCommand,
    RunMemoryCommandOut,
    RunMemoryItem,
    RunMemoryOut,
)
from app.services.guardrail_service import GuardrailService

_settings = MemorySettings()

_KIND_TITLES = {
    MemoryKind.PREFERENCE: "Préférences",
    MemoryKind.HABIT: "Habitudes",
    MemoryKind.CONTEXT: "Contexte",
    MemoryKind.FACT: "Faits",
}

# What a person is told when a command cannot be carried out, by the state of the memory in that run.
_STATE_MESSAGES = {
    "temporary": "Cette conversation est temporaire : je n'y retiens rien et je n'y lis pas votre mémoire. "
    "Réactivez la mémoire depuis la zone de saisie, ou ouvrez une autre conversation.",
    "unavailable": "La mémoire sert dans votre chat personnel : elle n'est pas utilisée dans un assistant, une routine "
    "ni par l'API. Retenez-le depuis le chat, ou depuis la page « Ma mémoire ».",
    "disabled": "Votre mémoire est désactivée : activez-la depuis la page « Ma mémoire » pour que je retienne quelque "
    "chose.",
    "suspended": "La mémoire n'est pas disponible sur cette installation.",
}


class MemoryRequestError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MemoryItemNotFoundError(Exception):
    pass


def available() -> bool:
    return _settings.MEMORY_ENABLED


class MemoryService:
    """What the assistant remembers of a person (#34, #282, #283, #284). Everything takes the person: nothing here
    reaches an item by its id alone, so no one reads, changes or deletes the memory of another."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.memories = MemoryRepository(db)

    # -- the person's own view --

    async def overview(self, user: RequestContext) -> MemoryOut:
        return MemoryOut(
            enabled=await self.memories.enabled(user.user_id),
            available=available(),
            max_items=_settings.MEMORY_MAX_ITEMS,
            value_max_chars=_settings.MEMORY_VALUE_MAX_CHARS,
            items=[MemoryItemOut.model_validate(item) for item in await self.memories.items(user.user_id)],
        )

    async def export(self, user: RequestContext) -> MemoryExportOut:
        overview = await self.overview(user)
        return MemoryExportOut(exported_at=datetime.now(UTC), enabled=overview.enabled, items=overview.items)

    async def set_enabled(self, user: RequestContext, enabled: bool) -> None:
        await self.memories.set_enabled(user.user_id, enabled)
        await self.db.commit()

    async def add(self, user: RequestContext, kind: MemoryKind, value: str) -> tuple[UserMemory, bool]:
        """Something the person asks to be remembered. It is theirs from then on (`explicit`): what is learned never
        overwrites it. Said again, it is the same item, not a second one. Returns the item and whether it was new."""
        value = await self._acceptable(user, value)
        key = key_of(value)
        item = await self.memories.by_key(user.user_id, kind, key)
        if item is None:
            if await self.memories.count(user.user_id) >= _settings.MEMORY_MAX_ITEMS:
                raise MemoryRequestError(
                    "limite",
                    f"Vous avez atteint les {_settings.MEMORY_MAX_ITEMS} éléments : supprimez-en avant d'en ajouter.",
                )
            item = await self.memories.add(
                UserMemory(user_id=user.user_id, kind=kind, key=key, value=value, origin=MemoryOrigin.EXPLICIT)
            )
            created = True
        else:
            item.value = value
            item.origin = MemoryOrigin.EXPLICIT
            item.confidence = 1.0
            item.evidence_count += 1
            item.enabled = True
            created = False
        await self.db.commit()
        await self.db.refresh(item)
        return item, created

    async def update(
        self, user: RequestContext, item_id: uuid.UUID, value: str | None, enabled: bool | None
    ) -> UserMemory:
        item = await self.memories.get(user.user_id, item_id)
        if item is None:
            raise MemoryItemNotFoundError
        if value is not None and value != item.value:
            item.value = await self._acceptable(user, value)
            # Corrected by the person: it is theirs, whoever wrote it first.
            item.origin = MemoryOrigin.EXPLICIT
            item.confidence = 1.0
        if enabled is not None:
            item.enabled = enabled
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, user: RequestContext, item_id: uuid.UUID) -> None:
        item = await self.memories.get(user.user_id, item_id)
        if item is None:
            raise MemoryItemNotFoundError
        if item.origin == MemoryOrigin.INFERRED:
            # What the person removes of what was learned does not come back with the next 👍 (#285).
            await self.memories.forget_learning_before_now(user.user_id)
        await self.memories.delete(item)
        await self.db.commit()

    async def delete_all(self, user: RequestContext) -> int:
        await self.memories.forget_learning_before_now(user.user_id)
        count = await self.memories.delete_all(user.user_id)
        await self.db.commit()
        return count

    async def stats(self) -> MemoryStatsOut:
        return MemoryStatsOut(available=available(), **await self.memories.counts())

    async def _acceptable(self, user: RequestContext, value: str) -> str:
        """The sentence to keep. The rules of what is never kept, then the guardrails of the administrator (#516): a
        secret or an identifier refused in a message is not kept in a memory either."""
        try:
            value = check(value)
        except MemoryRefusedError as error:
            raise MemoryRequestError(error.code, str(error)) from error
        decision = await GuardrailService(self.db).screen_text(user, value)
        if decision.blocked:
            raise MemoryRequestError("refuse", decision.message or "Ce texte ne peut pas être retenu.")
        # What the guardrails masked is what is kept.
        return check(decision.text)

    # -- the agent's view, of one run --

    async def state_of(self, run: Run) -> str:
        if not available():
            return "suspended"
        if run.memory_mode != "on":
            return run.memory_mode
        return "on" if await self.memories.enabled(run.user_id) else "disabled"

    async def for_run(self, run_id: uuid.UUID) -> RunMemoryOut | None:
        """What a run may read of its person's memory: nothing unless it is on for this run, and no more than fits the
        prompt - what the person wrote first, then the most certain."""
        run = await RunRepository(self.db).get_by_id(run_id)
        if run is None:
            return None
        state = await self.state_of(run)
        if state != "on":
            return RunMemoryOut(state=state)
        items: list[RunMemoryItem] = []
        used = 0
        for item in await self.memories.usable(run.user_id):
            if used + len(item.value) > _settings.MEMORY_PROMPT_MAX_CHARS:
                continue
            used += len(item.value)
            items.append(RunMemoryItem(id=item.id, kind=item.kind, value=item.value))
        return RunMemoryOut(state="on", items=items)

    async def record_use(self, run_id: uuid.UUID, ids: list[uuid.UUID]) -> bool:
        """The items that shaped the answer of a run: counted on the run - the person is told - and dated."""
        run = await RunRepository(self.db).get_by_id(run_id)
        if run is None:
            return False
        if await self.state_of(run) == "on":
            await self.memories.touch(run.user_id, ids)
            run.memory_used = len(ids)
            await self.db.commit()
        return True

    async def command(self, run_id: uuid.UUID, body: RunMemoryCommand) -> RunMemoryCommandOut | None:
        """What the person asked of their memory in the chat - "remember that…", "forget that…", "what do you know of
        me?" - carried out under the same rules as the page, and said in words."""
        run = await RunRepository(self.db).get_by_id(run_id)
        if run is None:
            return None
        state = await self.state_of(run)
        if state != "on":
            return RunMemoryCommandOut(outcome=state, message=_STATE_MESSAGES[state])
        user = RequestContext(
            user_id=run.user_id, email="", roles=[], is_admin=run.user_is_admin, groups=list(run.user_groups or [])
        )
        if body.action == "show":
            return await self._show(user)
        if body.action == "forget":
            return await self._forget(user, body.text)
        return await self._remember(user, body)

    async def _remember(self, user: RequestContext, body: RunMemoryCommand) -> RunMemoryCommandOut:
        try:
            item, created = await self.add(user, body.kind, body.text)
        except MemoryRequestError as error:
            return RunMemoryCommandOut(outcome="refused", message=error.message)
        verb = "C'est noté" if created else "C'était déjà noté, je l'ai mis à jour"
        return RunMemoryCommandOut(
            outcome="saved" if created else "updated",
            message=f"{verb} : « {item.value} ». Vous retrouvez et corrigez tout dans « Ma mémoire ».",
        )

    async def _forget(self, user: RequestContext, text: str) -> RunMemoryCommandOut:
        words = [word for word in fold(text).split() if len(word) >= 3]
        found = (
            [
                item
                for item in await self.memories.items(user.user_id)
                if all(word in fold(item.value) for word in words)
            ]
            if words
            else []
        )
        if not found:
            return RunMemoryCommandOut(
                outcome="not_found",
                message="Je ne trouve rien de tel dans votre mémoire. Elle est dans « Ma mémoire ».",
            )
        if len(found) > 1:
            listed = "\n".join(f"- {item.value}" for item in found[:10])
            return RunMemoryCommandOut(
                outcome="several",
                message=f"Plusieurs éléments correspondent, je n'en ai supprimé aucun :\n{listed}\n"
                "Précisez lequel, ou supprimez-le dans « Ma mémoire ».",
            )
        value = found[0].value
        await self.memories.delete(found[0])
        await self.db.commit()
        return RunMemoryCommandOut(outcome="deleted", message=f"C'est oublié : « {value} ».")

    async def _show(self, user: RequestContext) -> RunMemoryCommandOut:
        items = await self.memories.items(user.user_id)
        if not items:
            return RunMemoryCommandOut(
                outcome="listed",
                message="Je ne retiens rien de vous pour l'instant. Dites-moi « retiens que… » pour que ça change.",
            )
        lines = ["Voici ce que je retiens de vous :"]
        for kind, title in _KIND_TITLES.items():
            of_kind = [item for item in items if item.kind == kind]
            if of_kind:
                lines.append(f"\n**{title}**")
                lines += [f"- {item.value}" + ("" if item.enabled else " (désactivé)") for item in of_kind]
        lines.append("\nVous pouvez tout corriger, supprimer ou exporter dans « Ma mémoire ».")
        return RunMemoryCommandOut(outcome="listed", message="\n".join(lines))
