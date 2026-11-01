from pydantic_settings import BaseSettings, SettingsConfigDict


class ImageSettings(BaseSettings):
    """The generation of images in the chat (#518). What an administrator turns on, and the address, model and quotas,
    are settings of the application (Administration -> Images); these are the limits that no setting may lift."""

    # How many generations one person may start per minute, all attempts counted: a provider that fails is still a call.
    IMAGES_PER_USER_PER_MINUTE: int = 5
    # The prompt is cut here: it goes to a third party, and a long text is not a better image.
    IMAGES_PROMPT_MAX_CHARS: int = 4000
    # How long the provider has to make an image, and how long an image it gave by address has to be fetched (seconds).
    IMAGES_REQUEST_TIMEOUT_SECONDS: float = 120.0
    IMAGES_DOWNLOAD_TIMEOUT_SECONDS: float = 20.0
    # The most images one run of the assistant may ask for (#518): a question that makes it draw a dozen is not one.
    IMAGES_PER_RUN: int = 2
    # The most an administrator may allow for one image (bytes), and the largest side one may have (pixels).
    IMAGES_MAX_BYTES_LIMIT: int = 25 * 1024 * 1024
    IMAGES_MAX_SIDE: int = 8192

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
