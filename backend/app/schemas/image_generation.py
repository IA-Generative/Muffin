import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SIZE_PATTERN = re.compile(r"^(auto|\d{2,5}x\d{2,5})$")
QUALITIES = ("auto", "low", "medium", "high", "standard", "hd")


class ImageSettingsOut(BaseModel):
    """What the administrator sees of the settings. The key is never in it: only whether there is one."""

    enabled: bool
    # What is called: the address typed, or the hub's when none was.
    base_url: str | None
    uses_hub_address: bool
    has_key: bool
    # Whether the hub's own address and key can be used, for an administrator who types neither.
    hub_available: bool
    model: str | None
    # The model that retouches an image; None: the same as the one that draws.
    edit_model: str | None
    size: str
    quality: str | None
    daily_limit: int
    max_image_bytes: int
    allowed_groups: list[str]
    # Whether people could generate with these settings: enabled, with a model and a key.
    ready: bool


class ImageSettingsUpdate(BaseModel):
    """The settings changed (the others are left as they are). `base_url` empty or null: the hub's. `api_key`: a new
    key, kept encrypted; `clear_key`: forget the one there is."""

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=500)
    clear_key: bool = False
    model: str | None = Field(default=None, max_length=200)
    edit_model: str | None = Field(default=None, max_length=200)
    size: str | None = Field(default=None, max_length=20)
    quality: str | None = Field(default=None, max_length=20)
    daily_limit: int | None = Field(default=None, ge=1, le=1000)
    max_image_bytes: int | None = Field(default=None, ge=100 * 1024)
    allowed_groups: list[str] | None = Field(default=None, max_length=50)

    @field_validator("size")
    @classmethod
    def _size(cls, value: str | None) -> str | None:
        if value is not None and not SIZE_PATTERN.match(value):
            raise ValueError("La taille doit être « auto » ou de la forme 1024x1024.")
        return value

    @field_validator("quality")
    @classmethod
    def _quality(cls, value: str | None) -> str | None:
        if value and value not in QUALITIES:
            raise ValueError(f"La qualité doit être l'une de : {', '.join(QUALITIES)}.")
        return value

    @field_validator("allowed_groups")
    @classmethod
    def _groups(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [group.strip() for group in value if group.strip()]
        if any(len(group) > 200 for group in cleaned):
            raise ValueError("Un nom de groupe est trop long.")
        return list(dict.fromkeys(cleaned))


class ImageTestOut(BaseModel):
    """The result of the administrator's test: an image, or what went wrong in words that help (never the key)."""

    ok: bool
    code: str | None = None
    message: str | None = None
    duration_ms: int
    # How the provider answered: `b64_json` or `url`.
    response_format: str | None = None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    # The image as a data address, for the page to show; it is not kept anywhere.
    image: str | None = None


class ImageStatusOut(BaseModel):
    """What the chat needs to know to offer the mode «Image» to the person: it is not offered unless it can be used."""

    available: bool
    size: str | None = None
    daily_limit: int | None = None
    remaining_today: int | None = None
    max_prompt_chars: int | None = None


class ImageGenerationIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    conversation_id: uuid.UUID | None = None
    # Images attached in the composer (#512): with them, the request is a retouching of those images.
    image_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class ImageOut(BaseModel):
    id: uuid.UUID
    # "generated": a model made it (#518); "attached": the person attached it to their message (#512).
    origin: Literal["generated", "attached"]
    # What the model was asked to draw, and with which model: for a generated image only.
    prompt: str | None = None
    model: str | None = None
    content_type: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
    # True for every image a model made: the chat shows it as such, on the image.
    ai_generated: bool = False


class GeneratedMessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    images: list[ImageOut] = []


class ImageGenerationOut(BaseModel):
    conversation_id: uuid.UUID
    user_message: GeneratedMessageOut
    message: GeneratedMessageOut
