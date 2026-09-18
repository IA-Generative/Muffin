import hashlib
import hmac

from app.config import SharingSettings

# Exposed as a module attribute (rather than closed over) so tests can swap it out with
# monkeypatch.setattr without a real SHARE_INVITE_PEPPER configured.
_sharing_settings = SharingSettings()


class SharingNotConfiguredError(Exception):
    """Raised instead of silently hashing without a pepper - see SHARE_INVITE_PEPPER."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_group(group: str) -> str:
    # The exact path/name Keycloak puts in the token's `groups` claim (e.g. "/engineering"),
    # not a free-form label - only case is normalized, the rest must match verbatim.
    return group.strip().lower()


def hash_identifier(value: str) -> str:
    """HMAC-SHA256, not a plain hash: emails and group names have too little entropy to resist
    a dictionary attack against a leaked hash column with a bare SHA256. The pepper (server-side
    secret, never stored alongside the hashes) is what makes that attack infeasible."""
    if not _sharing_settings.SHARE_INVITE_PEPPER:
        raise SharingNotConfiguredError("SHARE_INVITE_PEPPER is not configured")
    return hmac.new(
        _sharing_settings.SHARE_INVITE_PEPPER.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def mask_email(email: str) -> str:
    """Non-reversible display hint for a pending/active user share - shows enough for the owner
    to recognize what they typed, never enough to reconstitute the full address from the UI."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    masked_local = f"{local[0]}***" if local else "***"
    domain_parts = domain.split(".")
    masked_domain = ".".join([f"{part[0]}***" if part else part for part in domain_parts])
    return f"{masked_local}@{masked_domain}"


def mask_group(group: str) -> str:
    """Same non-reversible-display principle as mask_email, applied to a group path/name."""
    stripped = group.strip().lstrip("/")
    return f"{stripped[0]}***" if stripped else "***"
