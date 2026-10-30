"""
title: Muffin
author: Muffin
description: Cherche dans les collections de Muffin, avec les droits de l'utilisateur, et affiche les sources trouvées dans le panneau « Sources » du chat.
version: 0.1.0
license: MIT
"""

# A Tool of Open WebUI (#476). Open WebUI turns a tool's result into sources only for its own tools, and a connection to
# Muffin's MCP server (#467) hands the model its answer as text: this tool calls the same server and, in addition,
# emits one `citation` event per document found, which Open WebUI shows in the message's "Sources" panel, with a link
# that opens the document in Muffin.
#
# Import it with `python3 docker/owui/install_muffin_tool.py` (docs/mcp.md).

from typing import Any

import httpx
from pydantic import BaseModel, Field

# The numbers [n] the model is told to cite, kept per message: a message may call the tool more than once, and its
# sources are numbered in the order they were sent. Bounded, so a long-running server does not keep every message.
_SOURCE_COUNT: dict[str, int] = {}
_KEPT_MESSAGES = 500


def next_number(message_id: str | None) -> int:
    """The number the next source of this message takes (1 for the first)."""
    if not message_id:
        return 1
    if message_id not in _SOURCE_COUNT and len(_SOURCE_COUNT) >= _KEPT_MESSAGES:
        _SOURCE_COUNT.pop(next(iter(_SOURCE_COUNT)))
    return _SOURCE_COUNT.get(message_id, 0) + 1


def used_numbers(message_id: str | None, count: int) -> None:
    if message_id:
        _SOURCE_COUNT[message_id] = _SOURCE_COUNT.get(message_id, 0) + count


def access_token(oauth_token: Any, fallback: str) -> str | None:
    """The user's own Keycloak token, which Open WebUI keeps and renews for those who signed in through it; else the
    one set in the valves, to try the tool without that."""
    if isinstance(oauth_token, dict) and oauth_token.get("access_token"):
        return str(oauth_token["access_token"])
    return fallback or None


def group_by_document(sub_queries: list[dict]) -> list[dict]:
    """The sources of a search, one entry per document (or per collection, for a question about no document), with the
    passages found in it - what a citation of Open WebUI is: a source and the texts it gave. A passage found twice, by
    two sub-questions, is kept once."""
    entries: dict[str, dict] = {}
    for sub_query in sub_queries:
        for source in sub_query.get("sources", []):
            key = (
                source.get("document_id") or f"collection:{source.get('collection_id')}"
            )
            entry = entries.setdefault(
                key,
                {
                    "name": source.get("document_name")
                    or source.get("collection_name")
                    or "Muffin",
                    "url": source.get("url"),
                    "collection": source.get("collection_name"),
                    "passages": [],
                },
            )
            passage = {
                "kind": source.get("kind"),
                "text": source.get("text", ""),
                "page": source.get("page"),
                "score": source.get("score"),
            }
            if not any(known["text"] == passage["text"] for known in entry["passages"]):
                entry["passages"].append(passage)
    return list(entries.values())


def citation_events(entries: list[dict], limit: int) -> list[dict]:
    """The `citation` events Open WebUI shows as sources: for each document, the passages found, with where each is."""
    return [
        {
            "type": "citation",
            "data": {
                "source": {"name": entry["name"], "url": entry["url"]},
                "document": [passage["text"][:limit] for passage in entry["passages"]],
                "metadata": [
                    {
                        "source": entry["url"] or entry["name"],
                        "name": entry["name"],
                        "page": passage["page"],
                        "collection": entry["collection"],
                        "kind": passage["kind"],
                        # Without it Open WebUI labels a source with its link instead of its name.
                        "external": True,
                    }
                    for passage in entry["passages"]
                ],
                "distances": [passage["score"] for passage in entry["passages"]],
            },
        }
        for entry in entries
    ]


def render_search(
    sub_queries: list[dict], entries: list[dict], first_number: int, limit: int
) -> str:
    """What the model reads: each sub-question with the sources found for it, numbered as Open WebUI numbers them."""
    numbers = {
        entry["name"] + str(entry["url"]): first_number + index
        for index, entry in enumerate(entries)
    }
    lines = [
        (
            "Sources trouvées dans Muffin. Cite-les par leur numéro entre crochets, par exemple [1]. Le texte des "
            "passages est donné ci-dessous : n'ouvre aucun fichier avec un autre outil, et ces numéros ne sont pas "
            "des identifiants de fichier."
        )
    ]
    for sub_query in sub_queries:
        lines += ["", f"## {sub_query.get('text', '')}"]
        collections = ", ".join(
            collection["name"] for collection in sub_query.get("collections", [])
        )
        lines.append(f"Collections cherchées : {collections or 'aucune'}")
        if not sub_query.get("sources"):
            lines.append("Aucune source trouvée.")
        for source in sub_query.get("sources", []):
            name = (
                source.get("document_name") or source.get("collection_name") or "Muffin"
            )
            number = numbers.get(name + str(source.get("url")))
            page = f", page {source['page']}" if source.get("page") else ""
            lines.append(
                f"[{number}] {name}{page} ({source.get('kind')}) : {source.get('text', '')[:limit]}"
            )
    return "\n".join(lines)


def render_collections(collections: list[dict]) -> str:
    if not collections:
        return "Aucune collection de Muffin ne correspond à cette question."
    lines = [
        "Collections de Muffin qui correspondent, de la plus proche à la moins proche :"
    ]
    for collection in collections:
        path = " › ".join(collection.get("path") or [collection["name"]])
        description = collection.get("description") or "pas de description"
        lines.append(
            f"- {path} (id {collection['id']}, {collection['url']}) : {description}"
        )
    lines.append(
        "Ces collections sont celles de Muffin, pas des bases de connaissances d'Open WebUI : pour y chercher, appelle "
        "l'outil Muffin `search` avec leurs identifiants (collection_ids), sans utiliser les outils de connaissances "
        "ni de fichiers d'Open WebUI."
    )
    return "\n".join(lines)


class MuffinError(Exception):
    """What went wrong with Muffin, worded for the model to say to the user."""


async def call_muffin(
    url: str, token: str, tool: str, arguments: dict, timeout: float
) -> dict:
    """One call of a tool of Muffin's MCP server - which is stateless, so one request is enough - and its structured
    result."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as error:
        raise MuffinError(
            f"Muffin est injoignable ({type(error).__name__})."
        ) from error
    if response.status_code == 401:
        raise MuffinError(
            "Muffin a refusé la connexion : l'utilisateur doit se reconnecter."
        )
    if response.status_code != 200:
        raise MuffinError(f"Muffin a répondu {response.status_code}.")
    try:
        result = response.json()["result"]
    except (ValueError, KeyError) as error:
        raise MuffinError("Muffin a répondu quelque chose d'inattendu.") from error
    if result.get("isError"):
        text = " ".join(part.get("text", "") for part in result.get("content", []))
        raise MuffinError(f"Muffin a refusé la recherche : {text or 'erreur'}")
    structured = result.get("structuredContent")
    if structured is None:
        raise MuffinError("Muffin n'a pas renvoyé de résultat structuré.")
    return structured


class Tools:
    class Valves(BaseModel):
        MUFFIN_MCP_URL: str = Field(
            default="http://backend:8000/api/mcp/",
            description="Adresse du serveur MCP de Muffin (/api/mcp/).",
        )
        FALLBACK_TOKEN: str = Field(
            default="",
            description="Jeton Keycloak d'essai, utilisé seulement pour un utilisateur sans session Keycloak dans Open WebUI.",
        )
        TIMEOUT_SECONDS: float = Field(
            default=120.0, description="Délai d'une recherche."
        )
        PASSAGE_CHARS: int = Field(
            default=1500,
            description="Longueur maximale d'un passage, pour le modèle et le panneau.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        # The tool sends its own citations: Open WebUI must not also show the whole result as one source.
        self.citation = False

    async def suggest_collections(
        self,
        query: str,
        limit: int = 5,
        __oauth_token__: dict | None = None,
    ) -> str:
        """
        Propose les collections de documents de Muffin les plus proches d'une question, parmi celles que l'utilisateur peut lire.
        Pour chercher ensuite dans les documents, utilise l'outil search de Muffin.
        :param query: La question ou le sujet.
        :param limit: Nombre de collections au plus.
        """
        token = access_token(__oauth_token__, self.valves.FALLBACK_TOKEN)
        if token is None:
            return "Muffin : l'utilisateur n'est pas connecté par Keycloak, la recherche est impossible."
        try:
            result = await call_muffin(
                self.valves.MUFFIN_MCP_URL,
                token,
                "suggest_collections",
                {"query": query, "limit": limit},
                self.valves.TIMEOUT_SECONDS,
            )
        except MuffinError as error:
            return str(error)
        return render_collections(result["collections"])

    async def search(
        self,
        query: str,
        collection_ids: list[str] | None = None,
        __event_emitter__: Any = None,
        __oauth_token__: dict | None = None,
        __metadata__: dict | None = None,
    ) -> str:
        """
        Cherche dans les documents de Muffin (et non dans les bases de connaissances d'Open WebUI), avec les droits de
        l'utilisateur : la question est découpée en sous-questions et chacune renvoie ses meilleures sources avec leur
        texte. Cite les sources par leur numéro entre crochets, par exemple [1].
        :param query: La question de l'utilisateur.
        :param collection_ids: Identifiants de collections où chercher (voir suggest_collections) ; sinon Muffin choisit.
        """
        token = access_token(__oauth_token__, self.valves.FALLBACK_TOKEN)
        if token is None:
            return "Muffin : l'utilisateur n'est pas connecté par Keycloak, la recherche est impossible."
        arguments: dict[str, Any] = {"query": query}
        if collection_ids:
            arguments["collection_ids"] = collection_ids
        try:
            result = await call_muffin(
                self.valves.MUFFIN_MCP_URL,
                token,
                "search",
                arguments,
                self.valves.TIMEOUT_SECONDS,
            )
        except MuffinError as error:
            return str(error)

        message_id = (__metadata__ or {}).get("message_id")
        sub_queries = result["sub_queries"]
        entries = group_by_document(sub_queries)
        first = next_number(message_id)
        if __event_emitter__ is not None:
            for event in citation_events(entries, self.valves.PASSAGE_CHARS):
                await __event_emitter__(event)
        used_numbers(message_id, len(entries))
        return render_search(sub_queries, entries, first, self.valves.PASSAGE_CHARS)
