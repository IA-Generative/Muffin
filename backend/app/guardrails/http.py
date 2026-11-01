"""The guardrails of type `http` (#516): a service outside, with a contract that is fixed.

Muffin calls `POST <url>` with `{"text": "...", "language": "fr"}` and, when a key is set,
`Authorization: Bearer <key>`.
The service answers `200` with `{"flagged": bool, "category": str|null, "score": 0..1|null, "redacted_text": str|null}`
(`redacted_text` only for a service that masks by itself: Presidio, for instance). Anything else is an error, which the
guardrail's `on_error` decides.

The address is typed by an administrator only, and is held to the same rules as any call out of the application: https,
a public address, no redirect, a short time. A host on a private network is reached only if it is in
`GUARDRAILS_ALLOWED_PRIVATE_HOSTS`. The key is a stored secret, never returned."""

from urllib.parse import urlsplit

import httpx

from app.config import GuardrailSettings
from app.core import url_guard
from app.guardrails.types import CLEAR, FLAGGED, Spec, Verdict

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = GuardrailSettings()

# What a service may answer at most: a verdict is a few bytes, and what it masks is no longer than the text.
MAX_RESPONSE_BYTES = 256 * 1024


class InvalidResponseError(ValueError):
    """The service did not answer with the contract."""


async def check_address(url: str) -> str:
    """The address, when this application may call it: its form, and a public host - or a private one that an
    administrator of the deployment listed. Raises UrlRefusedError otherwise."""
    host = (urlsplit(url).hostname or "").lower()
    if host and host in _settings.allowed_private_hosts:
        return url_guard.check_form(url, restrict_domains=False)
    return await url_guard.ensure_public(url, restrict_domains=False, https_only=True)


def _client(timeout: float) -> httpx.AsyncClient:
    """Injectable: tests give it a transport. No redirect is followed: it would be a way round the check of the host."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


def parse_response(body: object, text: str, *, accept_redaction: bool) -> Verdict:
    """The verdict in the answer of the service, or InvalidResponseError."""
    if not isinstance(body, dict) or not isinstance(body.get("flagged"), bool):
        raise InvalidResponseError("flagged is missing or is not a boolean")
    category, score, redacted = body.get("category"), body.get("score"), body.get("redacted_text")
    if category is not None and (not isinstance(category, str) or len(category) > 64):
        raise InvalidResponseError("bad category")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1):
        raise InvalidResponseError("score out of range")
    if redacted is not None and (not isinstance(redacted, str) or len(redacted) > 2 * len(text) + 1000):
        raise InvalidResponseError("bad redacted_text")
    flagged = body["flagged"]
    return Verdict(
        FLAGGED if flagged else CLEAR,
        category=category if flagged else None,
        score=float(score) if score is not None else None,
        redacted_text=redacted if flagged and accept_redaction else None,
    )


async def check(spec: Spec, text: str) -> Verdict:
    """The verdict of a guardrail of type `http`. Raises when the service cannot be reached or answers badly."""
    url = await check_address(str(spec.config.get("url") or ""))
    headers = {"Authorization": f"Bearer {spec.secret}"} if spec.secret else {}
    payload = {"text": text[: _settings.GUARDRAILS_TEXT_MAX_CHARS], "language": "fr"}
    async with _client(spec.timeout_ms / 1000) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
        raise InvalidResponseError(f"status {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise InvalidResponseError("not JSON") from error
    return parse_response(body, text, accept_redaction=spec.enforcement.value == "redact")
