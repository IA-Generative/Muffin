"""The generation of images in the chat (#518): optional, off by default, and done only when the person asks for it.

What is kept to, whatever the provider is:
- **Nothing is called before it is allowed.** The function must be on, the person allowed, the prompt in bounds, the
  quota left: otherwise the answer is a clear code and the provider has not been called.
- **Both answers of the protocol are taken.** No `response_format` is sent (a provider may refuse it); the image comes
  as `b64_json` or as an address. An address is fetched **by the server** - public, https, no redirect, short delay,
  bounded - and the image is stored by Muffin: the address of a third party is never given on.
- **The bytes are checked, not the sender's word**: a raster image (PNG, JPEG, WebP), of a bounded weight and size.
- **Nothing of the provider's reaches the person but a code**: not its text, not the key.

The image belongs to its conversation: stored under it, read by its owner only, deleted with it."""

import asyncio
import base64
import binascii
import re
import time
import uuid
from datetime import UTC, datetime

import httpx
from loguru import logger
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ImageSettings, LlmSettings
from app.connectors import async_redis
from app.core import image_bytes, storage, url_guard
from app.core.image_bytes import NotAnImageError
from app.core.secret_store import SecretStoreError
from app.core.security.factory import RequestContext
from app.models.image_generation import GeneratedImage, ImageGenerationSettings
from app.models.message import MessageRole
from app.models.token_usage import TokenUsageKind
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.generated_image_repository import GeneratedImageRepository, ImageSettingsRepository
from app.schemas.image_generation import (
    GeneratedMessageOut,
    ImageGenerationOut,
    ImageOut,
    ImageSettingsOut,
    ImageSettingsUpdate,
    ImageStatusOut,
    ImageTestOut,
)
from app.schemas.internal_pipeline import LlmUsageContext
from app.services.app_settings_service import NotAdminError
from app.services.secret_store_service import SecretNotFoundError, SecretStore
from app.services.usage_service import UsageService

# Module attributes so that tests change them with monkeypatch.setattr.
_settings = ImageSettings()
_llm_settings = LlmSettings()

_PURPOSE = "image-generation-key"
_DAY_TTL = 2 * 24 * 3600
_TEST_PROMPT = "Une étoile jaune sur un fond bleu uni, dessin très simple."
_REFUSAL_CODES = ("content_policy_violation", "moderation_blocked", "safety")


class ImageGenerationError(Exception):
    """A generation that did not happen, said with a code that does not change and words for the person. `status` is the
    HTTP status the API answers with."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ConversationNotFoundError(Exception):
    pass


class ImageNotFoundError(Exception):
    pass


def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    """The client of the provider. One per call: the address and the key can change between two, and a connection that
    stays open is no use for something the person does a few times a day."""
    return AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=_settings.IMAGES_REQUEST_TIMEOUT_SECONDS, max_retries=0
    )


def _download_client() -> httpx.AsyncClient:
    """The client that fetches an image the provider gave by address: it never follows a redirect (the address after it
    would not have been checked)."""
    return httpx.AsyncClient(follow_redirects=False, timeout=_settings.IMAGES_DOWNLOAD_TIMEOUT_SECONDS)


def _remember(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt).strip()


class ImageGenerationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = ImageSettingsRepository(db)
        self.images = GeneratedImageRepository(db)
        self.conversations = ConversationRepository(db)

    # --- the administrator's settings ---

    @staticmethod
    def _require_admin(user: RequestContext) -> None:
        if not user.is_admin:
            raise NotAdminError(user.user_id)

    @staticmethod
    def _hub_available() -> bool:
        return _llm_settings.is_configured

    def _present(self, row: ImageGenerationSettings) -> ImageSettingsOut:
        uses_hub = not row.base_url
        has_key = row.secret_id is not None or (uses_hub and bool(_llm_settings.OPENAI_API_KEY))
        return ImageSettingsOut(
            enabled=row.enabled,
            base_url=row.base_url or (_llm_settings.OPENAI_API_BASE_URL or None),
            uses_hub_address=uses_hub,
            has_key=row.secret_id is not None,
            hub_available=self._hub_available(),
            model=row.model,
            size=row.size,
            quality=row.quality,
            daily_limit=row.daily_limit,
            max_image_bytes=row.max_image_bytes,
            allowed_groups=list(row.allowed_groups or []),
            ready=bool(row.enabled and row.model and has_key and (row.base_url or self._hub_available())),
        )

    async def get_settings(self, user: RequestContext) -> ImageSettingsOut:
        self._require_admin(user)
        return self._present(await self.settings.get_or_create())

    async def update_settings(self, user: RequestContext, body: ImageSettingsUpdate) -> ImageSettingsOut:
        self._require_admin(user)
        row = await self.settings.get_or_create()
        changes = body.model_dump(exclude_unset=True, exclude={"api_key", "clear_key"})
        if "base_url" in changes:
            changes["base_url"] = await self._checked_address(changes["base_url"])
        if "model" in changes:
            changes["model"] = (changes["model"] or "").strip() or None
        if "quality" in changes:
            changes["quality"] = changes["quality"] or None
        if "max_image_bytes" in changes and changes["max_image_bytes"] > _settings.IMAGES_MAX_BYTES_LIMIT:
            raise ImageGenerationError(
                "reglage_invalide", "Cette taille maximale dépasse la limite de l'installation.", 422
            )
        for key, value in changes.items():
            if value is not None or key in ("base_url", "model", "quality"):
                setattr(row, key, value)
        if body.clear_key and row.secret_id is not None:
            await self._forget_key(row)
        elif body.api_key:
            await self._set_key(row, user, body.api_key.strip())
        self._check_consistent(row)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(f"Image generation settings changed by {user.user_id}: {', '.join(sorted(changes))}")
        return self._present(row)

    @staticmethod
    async def _checked_address(value: str | None) -> str | None:
        """The address of a provider: http(s), no credentials in it. It may be on the internal network - a gateway is
        often there - since it is typed by an administrator, unlike an address a provider sends back."""
        if not value or not value.strip():
            return None
        try:
            return url_guard.check_form(value, restrict_domains=False).rstrip("/")
        except url_guard.UrlRefusedError as error:
            raise ImageGenerationError("reglage_invalide", str(error), 422) from error

    def _check_consistent(self, row: ImageGenerationSettings) -> None:
        if row.base_url and row.base_url.rstrip("/") != _llm_settings.OPENAI_API_BASE_URL.rstrip("/"):
            if row.secret_id is None:
                # The hub's key is never sent to another address.
                raise ImageGenerationError(
                    "reglage_invalide", "Une autre adresse que celle du hub demande sa propre clé.", 422
                )
        if row.enabled and not (row.model or "").strip():
            raise ImageGenerationError("reglage_invalide", "Choisissez un modèle avant d'activer la fonction.", 422)

    async def _set_key(self, row: ImageGenerationSettings, user: RequestContext, key: str) -> None:
        store = SecretStore(self.db)
        if row.secret_id is None:
            row.secret_id = (await store.put(owner=None, purpose=_PURPOSE, plaintext=key, created_by=user.user_id)).id
        else:
            await store.replace(row.secret_id, key, owner=None, purpose=_PURPOSE)

    async def _forget_key(self, row: ImageGenerationSettings) -> None:
        if row.secret_id is not None:
            try:
                await SecretStore(self.db).delete(row.secret_id, owner=None, purpose=_PURPOSE)
            except SecretNotFoundError:
                pass
            row.secret_id = None

    async def _provider(self, row: ImageGenerationSettings) -> tuple[str, str]:
        """(address, key) to call: the administrator's, or the hub's - and the hub's key only for the hub's address."""
        base_url = row.base_url or _llm_settings.OPENAI_API_BASE_URL
        if row.secret_id is not None:
            try:
                key = await SecretStore(self.db).reveal(row.secret_id, owner=None, purpose=_PURPOSE)
            except (SecretNotFoundError, SecretStoreError):
                logger.warning("The key of the image provider could not be read")
                key = ""
        else:
            key = _llm_settings.OPENAI_API_KEY if not row.base_url else ""
        if not base_url or not key or not row.model:
            raise ImageGenerationError(
                "non_configuree", "La génération d'images n'est pas configurée complètement.", 409
            )
        return base_url, key

    # --- who may, and how many ---

    @staticmethod
    def _allowed(row: ImageGenerationSettings, user: RequestContext) -> bool:
        groups = list(row.allowed_groups or [])
        return user.is_admin or not groups or bool(set(groups) & set(user.groups))

    @staticmethod
    def _day_key(user_id: str) -> str:
        return f"images:day:{user_id}:{datetime.now(UTC).date().isoformat()}"

    async def _remaining_today(self, row: ImageGenerationSettings, user_id: str) -> int | None:
        try:
            used = int(await async_redis().get(self._day_key(user_id)) or 0)
        except Exception:
            logger.warning("The image quota could not be read", exc_info=True)
            return None
        return max(0, row.daily_limit - used)

    async def status(self, user: RequestContext) -> ImageStatusOut:
        """Whether the chat offers the mode «Image» to this person: only when the function is on, ready, and theirs."""
        row = await self.settings.get()
        if row is None or not row.enabled or not self._allowed(row, user):
            return ImageStatusOut(available=False)
        try:
            await self._provider(row)
        except ImageGenerationError:
            return ImageStatusOut(available=False)
        return ImageStatusOut(
            available=True,
            size=row.size,
            daily_limit=row.daily_limit,
            remaining_today=await self._remaining_today(row, user.user_id),
            max_prompt_chars=_settings.IMAGES_PROMPT_MAX_CHARS,
        )

    async def _take_quota(self, row: ImageGenerationSettings, user_id: str) -> None:
        """One unit of the minute's rate and of the day's quota, taken **before** the provider is called. A quota that
        cannot be checked stops the call: an image costs money, unlike the answer of a tool."""
        try:
            redis = async_redis()
            minute_key = f"images:min:{user_id}:{int(time.time() // 60)}"
            count = await redis.incr(minute_key)
            if count == 1:
                await redis.expire(minute_key, 90)
            if count > _settings.IMAGES_PER_USER_PER_MINUTE:
                raise ImageGenerationError(
                    "trop_de_demandes", "Trop de demandes à la suite : patientez un instant.", 429
                )
            day_key = self._day_key(user_id)
            used = await redis.incr(day_key)
            if used == 1:
                await redis.expire(day_key, _DAY_TTL)
            if used > row.daily_limit:
                await redis.decr(day_key)
                raise ImageGenerationError(
                    "quota_depasse",
                    f"Vous avez atteint votre limite de {row.daily_limit} images pour aujourd'hui.",
                    429,
                )
        except ImageGenerationError:
            raise
        except Exception as error:
            logger.warning("The image quota could not be checked", exc_info=True)
            raise ImageGenerationError(
                "quota_indisponible", "Votre limite d'images ne peut pas être vérifiée pour le moment.", 503
            ) from error

    @staticmethod
    async def _give_back_quota(user_id: str) -> None:
        """A generation that gave no image does not count against the day."""
        try:
            await async_redis().decr(ImageGenerationService._day_key(user_id))
        except Exception:
            logger.warning("The image quota could not be given back", exc_info=True)

    # --- calling the provider ---

    async def _ask_provider(
        self, row: ImageGenerationSettings, base_url: str, key: str, prompt: str
    ) -> tuple[bytes, str]:
        """The bytes of the image the provider made, and how it gave them (`b64_json` or `url`)."""
        arguments: dict = {"model": row.model, "prompt": prompt, "n": 1, "size": row.size}
        if row.quality:
            arguments["quality"] = row.quality
        # No `response_format`: some models refuse it, some answer only with base64, the others by address.
        client = _client(base_url, key)
        try:
            response = await client.images.generate(**arguments)
        except Exception as error:
            raise self._provider_error(error) from error
        finally:
            await client.close()
        item = response.data[0] if response.data else None
        if item is None:
            raise ImageGenerationError("image_invalide", "Le fournisseur n'a renvoyé aucune image.", 502)
        limit = row.max_image_bytes
        if getattr(item, "b64_json", None):
            # Base64 weighs a third more than what it holds: refused before it is decoded when it cannot fit.
            if len(item.b64_json) > limit * 4 // 3 + 8:
                raise ImageGenerationError("image_trop_lourde", "L'image produite est trop lourde.", 502)
            try:
                return base64.b64decode(item.b64_json, validate=True), "b64_json"
            except (binascii.Error, ValueError) as error:
                raise ImageGenerationError("image_invalide", "L'image du fournisseur est illisible.", 502) from error
        if getattr(item, "url", None):
            return await self._download(item.url, limit), "url"
        raise ImageGenerationError("image_invalide", "Le fournisseur n'a renvoyé aucune image.", 502)

    @staticmethod
    def _provider_error(error: Exception) -> ImageGenerationError:
        """What the provider's failure is called here. Nothing of its text goes on: it may repeat part of the key or of
        the prompt. The log has the status and the code."""
        status = getattr(error, "status_code", None)
        code = getattr(error, "code", None)
        logger.warning(f"The image provider failed: {type(error).__name__} status={status} code={code}")
        if isinstance(error, AuthenticationError | PermissionDeniedError):
            return ImageGenerationError("cle_refusee", f"Le fournisseur refuse la clé ou l'accès (HTTP {status}).", 502)
        if isinstance(error, NotFoundError):
            return ImageGenerationError(
                "modele_introuvable", "Le fournisseur ne connaît pas ce modèle (HTTP 404).", 502
            )
        if isinstance(error, BadRequestError):
            if code in _REFUSAL_CODES or "safety" in str(code or "").lower() or "policy" in str(code or "").lower():
                return ImageGenerationError(
                    "refus_politique", "Le fournisseur a refusé cette demande : reformulez-la.", 422
                )
            return ImageGenerationError(
                "parametre_refuse", "Le fournisseur refuse un paramètre de la demande (HTTP 400).", 502
            )
        if isinstance(error, RateLimitError):
            return ImageGenerationError(
                "fournisseur_surcharge", "Le fournisseur est saturé : réessayez plus tard.", 503
            )
        if isinstance(error, APITimeoutError):
            return ImageGenerationError("delai_depasse", "Le fournisseur a mis trop de temps à répondre.", 504)
        if isinstance(error, APIConnectionError):
            return ImageGenerationError("fournisseur_injoignable", "Le fournisseur d'images est injoignable.", 502)
        if isinstance(error, APIStatusError):
            return ImageGenerationError("fournisseur_en_erreur", f"Le fournisseur a échoué (HTTP {status}).", 502)
        return ImageGenerationError("fournisseur_en_erreur", "La génération a échoué.", 502)

    @staticmethod
    async def _download(url: str, limit: int) -> bytes:
        """An image the provider gave by address - a request driven by a third party, so: public addresses only, https,
        no redirect, a short delay, and never more than `limit` bytes."""
        try:
            await url_guard.ensure_public(url, restrict_domains=False, https_only=True)
        except url_guard.UrlRefusedError as error:
            logger.warning(f"An image address of the provider was refused: {error}")
            raise ImageGenerationError(
                "image_invalide", "L'adresse de l'image du fournisseur est refusée.", 502
            ) from error
        try:
            async with (
                _download_client() as http,
                http.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise ImageGenerationError(
                        "image_invalide", "L'image du fournisseur n'a pas pu être récupérée.", 502
                    )
                declared = int(response.headers.get("content-length") or 0)
                if declared > limit:
                    raise ImageGenerationError("image_trop_lourde", "L'image produite est trop lourde.", 502)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ImageGenerationError("image_trop_lourde", "L'image produite est trop lourde.", 502)
                return bytes(data)
        except ImageGenerationError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(f"The image of the provider could not be fetched: {type(error).__name__}")
            raise ImageGenerationError(
                "image_invalide", "L'image du fournisseur n'a pas pu être récupérée.", 502
            ) from error

    def _checked(self, data: bytes, row: ImageGenerationSettings) -> image_bytes.ImageInfo:
        if len(data) > row.max_image_bytes:
            raise ImageGenerationError("image_trop_lourde", "L'image produite est trop lourde.", 502)
        try:
            return image_bytes.inspect(data, max_side=_settings.IMAGES_MAX_SIDE)
        except NotAnImageError as error:
            raise ImageGenerationError(
                "image_invalide", f"L'image du fournisseur est refusée : {error}", 502
            ) from error

    # --- the administrator's test ---

    async def test(self, user: RequestContext) -> ImageTestOut:
        """A small image with the settings as they are, to see whether the provider answers: the time it took, and what
        went wrong if it did not. Not kept, not counted against anyone's quota."""
        self._require_admin(user)
        row = await self.settings.get_or_create()
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            base_url, key = await self._provider(row)
            data, how = await self._ask_provider(row, base_url, key, _TEST_PROMPT)
            info = self._checked(data, row)
        except ImageGenerationError as error:
            return ImageTestOut(ok=False, code=error.code, message=error.message, duration_ms=elapsed())
        return ImageTestOut(
            ok=True,
            duration_ms=elapsed(),
            response_format=how,
            content_type=info.content_type,
            width=info.width,
            height=info.height,
            size_bytes=len(data),
            image=f"data:{info.content_type};base64,{base64.b64encode(data).decode()}",
        )

    # --- the person's image ---

    async def generate(
        self, user: RequestContext, prompt: str, conversation_id: uuid.UUID | None
    ) -> ImageGenerationOut:
        row = await self.settings.get()
        if row is None or not row.enabled:
            raise ImageGenerationError("fonction_desactivee", "La génération d'images n'est pas activée.", 404)
        if not self._allowed(row, user):
            raise ImageGenerationError("non_autorise", "Vous n'avez pas le droit de générer des images.", 403)
        prompt = prompt.strip()
        if not prompt:
            raise ImageGenerationError("invite_vide", "Décrivez l'image à générer.", 422)
        if len(prompt) > _settings.IMAGES_PROMPT_MAX_CHARS:
            raise ImageGenerationError(
                "invite_trop_longue",
                f"La description est trop longue ({_settings.IMAGES_PROMPT_MAX_CHARS} caractères au plus).",
                422,
            )
        base_url, key = await self._provider(row)
        conversation = None
        if conversation_id is not None:
            conversation = await self.conversations.get(conversation_id, user.user_id)
            if conversation is None:
                raise ConversationNotFoundError(str(conversation_id))

        await self._take_quota(row, user.user_id)
        started = time.monotonic()
        try:
            data, _how = await self._ask_provider(row, base_url, key, prompt)
            info = self._checked(data, row)
        except ImageGenerationError:
            await self._give_back_quota(user.user_id)
            raise
        data = image_bytes.label_png(data)

        image_id = uuid.uuid4()
        if conversation is None:
            conversation = await self.conversations.create(user.user_id, title=_remember(prompt)[:80])
        key_in_bucket = f"images/{conversation.id}/{image_id}.{info.extension}"
        await asyncio.to_thread(storage.put_object, key_in_bucket, data, info.content_type)
        try:
            user_message = await self.conversations.add_message(conversation.id, MessageRole.USER, prompt)
            # Its own transaction: the history orders messages by creation time, which Postgres takes from the start of
            # the transaction - the answer must come after the request, not at the same instant.
            await self.db.commit()
            answer = await self.conversations.add_message(
                conversation.id,
                MessageRole.ASSISTANT,
                f"Image générée par IA à partir de la demande : « {_remember(prompt)[:200]} ».",
            )
            image = await self.images.add(
                GeneratedImage(
                    id=image_id,
                    conversation_id=conversation.id,
                    message_id=answer.id,
                    user_id=user.user_id,
                    prompt=prompt,
                    model=row.model or "",
                    s3_key=key_in_bucket,
                    content_type=info.content_type,
                    width=info.width,
                    height=info.height,
                    size_bytes=len(data),
                )
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            await asyncio.to_thread(storage.delete_objects, [key_in_bucket])
            await self._give_back_quota(user.user_id)
            raise

        # Made before the usage is written: a failure there rolls back the session, which forgets what it holds.
        result = ImageGenerationOut(
            conversation_id=conversation.id,
            user_message=GeneratedMessageOut(
                id=user_message.id, role="user", content=user_message.content, created_at=user_message.created_at
            ),
            message=GeneratedMessageOut(
                id=answer.id,
                role="assistant",
                content=answer.content,
                created_at=answer.created_at,
                images=[self.present_image(image)],
            ),
        )
        await self._record_usage(user, row.model or "", info)
        logger.info(
            f"Image {image_id} generated for {user.user_id} in {int((time.monotonic() - started) * 1000)} ms "
            f"({info.width}x{info.height}, {len(data)} bytes)"
        )
        return result

    async def _record_usage(self, user: RequestContext, model: str, info: image_bytes.ImageInfo) -> None:
        """What an image costs is its count and its size, not tokens: a row of the usage, step `image_generation`."""
        await UsageService(self.db).record(
            LlmUsageContext(step="image_generation", user_id=user.user_id),
            TokenUsageKind.IMAGE,
            model,
            0,
            0,
            images=1,
            pixels=info.width * info.height,
        )

    @staticmethod
    def present_image(image: GeneratedImage) -> ImageOut:
        return ImageOut(
            id=image.id,
            prompt=image.prompt,
            model=image.model,
            content_type=image.content_type,
            width=image.width,
            height=image.height,
            size_bytes=image.size_bytes,
            created_at=image.created_at,
        )
