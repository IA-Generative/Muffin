from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.app_settings import AppSettings
from app.models.image_generation import ImageGenerationSettings
from app.models.model_profile import DEFAULT_MODEL_SCORE, ModelProfile
from app.models.voice import VoiceEngineSettings
from app.repositories.app_settings_repository import SETTINGS_ID, AppSettingsRepository
from app.schemas.model_profiles import (
    AutoCandidate,
    AutoCandidatesOut,
    ModelCapability,
    ModelProfileOut,
    ModelProfilesOut,
    ModelProfileUpdate,
)


class NotAdminError(Exception):
    pass


class UnknownModelError(Exception):
    pass


async def hub_capabilities() -> dict[str, set[ModelCapability]]:
    """Every model the hub lists, with what it can do as far as the hub tells (chat, vision and embeddings are found by
    trying, once per cache lifetime). Empty when no hub is configured."""
    # Imported here: the module owns the hub client the tests swap out, and the probes' cache.
    from app.routers import internal_llm as hub

    if hub._openai_client is None:
        return {}
    available = await hub._openai_client.models.list()
    capabilities: dict[str, set[ModelCapability]] = {model.id: set() for model in available.data}
    probes = (
        (ModelCapability.CHAT, hub._CHAT_MODELS_CACHE_KEY, hub._supports_chat),
        (ModelCapability.VISION, hub._VISION_MODELS_CACHE_KEY, hub._supports_vision),
        (ModelCapability.EMBEDDINGS, hub._EMBEDDING_MODELS_CACHE_KEY, hub._supports_embeddings),
    )
    for capability, cache_key, probe in probes:
        for model_id in await hub._discover_models(cache_key, probe):
            capabilities.setdefault(model_id, set()).add(capability)
    return capabilities


class ModelCatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _configured_capabilities(self) -> dict[str, set[ModelCapability]]:
        """The models the image and voice settings point at: the hub does not say what they are for."""
        found: dict[str, set[ModelCapability]] = {}
        images = await self.db.get(ImageGenerationSettings, 1)
        if images is not None:
            for model in (images.model, images.edit_model):
                if model:
                    found.setdefault(model, set()).add(ModelCapability.IMAGE_GENERATION)
        voice = await self.db.get(VoiceEngineSettings, 1)
        if voice is not None:
            if voice.stt_model:
                found.setdefault(voice.stt_model, set()).add(ModelCapability.SPEECH_TO_TEXT)
            if voice.tts_model:
                found.setdefault(voice.tts_model, set()).add(ModelCapability.TEXT_TO_SPEECH)
        return found

    async def _profiles(self) -> dict[str, ModelProfile]:
        rows = (await self.db.execute(select(ModelProfile))).scalars().all()
        return {row.model_id: row for row in rows}

    async def _all_capabilities(self) -> dict[str, set[ModelCapability]]:
        capabilities = await hub_capabilities()
        for model_id, extra in (await self._configured_capabilities()).items():
            capabilities.setdefault(model_id, set()).update(extra)
        return capabilities

    async def list_profiles(self, user: RequestContext) -> ModelProfilesOut:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        capabilities = await self._all_capabilities()
        profiles = await self._profiles()
        # A model that was described and is gone from the hub stays in the list: the description is not lost if the hub
        # is unreachable for a moment.
        models = [
            self._out(model_id, capabilities.get(model_id, set()), profiles.get(model_id))
            for model_id in sorted(capabilities.keys() | profiles.keys())
        ]
        settings = await AppSettingsRepository(self.db).get()
        return ModelProfilesOut(models=models, classifier_model=settings.classifier_model if settings else None)

    @staticmethod
    def _out(model_id: str, capabilities: set[ModelCapability], profile: ModelProfile | None) -> ModelProfileOut:
        return ModelProfileOut(
            id=model_id,
            capabilities=sorted(capabilities),
            score=profile.score if profile else DEFAULT_MODEL_SCORE,
            description=profile.description if profile else None,
            auto_enabled=profile.auto_enabled if profile else True,
            described=profile is not None,
        )

    async def update_profile(self, user: RequestContext, model_id: str, update: ModelProfileUpdate) -> ModelProfileOut:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        capabilities = await self._all_capabilities()
        profile = await self.db.get(ModelProfile, model_id)
        if model_id not in capabilities and profile is None:
            raise UnknownModelError(model_id)
        if profile is None:
            profile = ModelProfile(model_id=model_id)
            self.db.add(profile)
        profile.score = update.score
        profile.description = (update.description or "").strip() or None
        profile.auto_enabled = update.auto_enabled
        await self.db.commit()
        return self._out(model_id, capabilities.get(model_id, set()), profile)

    async def set_classifier_model(self, user: RequestContext, model_id: str | None) -> str | None:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        if model_id is not None and ModelCapability.CHAT not in (await self._all_capabilities()).get(model_id, set()):
            raise UnknownModelError(model_id)
        settings = await self.db.get(AppSettings, SETTINGS_ID)
        if settings is None:
            settings = AppSettings(id=SETTINGS_ID)
            self.db.add(settings)
        settings.classifier_model = model_id
        await self.db.commit()
        return model_id

    async def auto_candidates(self) -> AutoCandidatesOut:
        """The chat models the automatic choice may pick, cheapest first, and the one that classifies (None: the first
        of them)."""
        capabilities = await hub_capabilities()
        profiles = await self._profiles()
        candidates = [
            AutoCandidate(
                model=model_id,
                score=profiles[model_id].score if model_id in profiles else DEFAULT_MODEL_SCORE,
                description=profiles[model_id].description if model_id in profiles else None,
                vision=ModelCapability.VISION in caps,
            )
            for model_id, caps in capabilities.items()
            if ModelCapability.CHAT in caps and (model_id not in profiles or profiles[model_id].auto_enabled)
        ]
        candidates.sort(key=lambda candidate: (candidate.score, candidate.model))
        settings = await AppSettingsRepository(self.db).get()
        chosen = settings.classifier_model if settings else None
        return AutoCandidatesOut(
            candidates=candidates,
            classifier_model=chosen if chosen and any(c.model == chosen for c in candidates) else None,
        )
