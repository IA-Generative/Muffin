"""Where a tool server may be (#343): the guard against the server-side request forgery.

A tool server is an address a user types, that Muffin then calls from inside its own network. Left unchecked it is a way
to reach what the user cannot: the other services of the cluster, the metadata of the cloud, the local machine. So the
address is checked for its form (scheme, no credentials in it, an allowed domain) **and for what it resolves to**: every
address its name resolves to must be a public one. It is checked when the server is added **and again at each call**,
which narrows - it does not close - the window of a name that answers a public address first and a private one later
(DNS rebinding): the lasting answer to that is an egress policy on the network, which is no business of the code."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import ToolSettings

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ToolSettings()

_SCHEMES = ("http", "https")


class UrlRefusedError(Exception):
    """The address may not be a tool server's. The reason is for the person who typed it, never about the network."""


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # `is_global` is false for private, loopback, link-local (the cloud metadata address), reserved, shared (CGNAT)...
    mapped = getattr(address, "ipv4_mapped", None)
    address = mapped or address
    # `is_global` alone lets multicast through: it is checked on its own as well.
    return address.is_global and not (
        address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_private
    )


def check_form(url: str) -> str:
    """The URL if its form is acceptable: http(s), a host, no credentials, an allowed domain."""
    if len(url) > 2048:
        raise UrlRefusedError("L'adresse est trop longue.")
    parts = urlsplit(url.strip())
    if parts.scheme not in _SCHEMES:
        raise UrlRefusedError("L'adresse doit commencer par http:// ou https://.")
    if parts.username or parts.password:
        raise UrlRefusedError("L'adresse ne doit contenir ni identifiant ni mot de passe.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlRefusedError("L'adresse n'a pas de nom de serveur.")
    allowed = _settings.allowed_domains
    if allowed and not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise UrlRefusedError("Ce domaine n'est pas autorisé pour un serveur d'outils.")
    return url.strip()


async def ensure_public(url: str) -> str:
    """The URL, once its form is right and every address its host resolves to is a public one. Resolution runs off the
    event loop. An address that does not resolve is refused as well: there is nothing to call."""
    url = check_form(url)
    if _settings.TOOLS_ALLOW_PRIVATE_ADDRESSES:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().run_in_executor(
                None, lambda: socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
            )
        except OSError as error:
            raise UrlRefusedError("Ce nom de serveur ne se résout pas.") from error
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or not all(_is_public(address) for address in addresses):
        raise UrlRefusedError(
            "Cette adresse n'est pas publique : un serveur d'outils ne peut pas être sur le réseau interne."
        )
    return url
