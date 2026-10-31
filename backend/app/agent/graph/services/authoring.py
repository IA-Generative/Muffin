"""What the plan needs to tell a request to change or create a document from a question, and the words for it."""

import re
from typing import Any

# Verbs (French and English) of a request to change a document, and to write a new one. A cheap gate: most questions
# never contain one, and then neither the backend is asked what the user may edit nor is the plan shown it.
EDIT_VERBS = re.compile(
    r"\b(ajout\w*|rajout\w*|modifi\w*|supprim\w*|retir\w*|enlèv\w*|enlev\w*|remplac\w*|corrig\w*|chang\w*|"
    r"mets? à jour|mettre à jour|mise à jour|insèr\w*|insér\w*|réécri\w*|reecri\w*|reformul\w*|complèt\w*|"
    r"renomm\w*|raccourc\w*|allong\w*|add|edit|update|remove|delete|replace|change|fix|insert|rewrite|"
    r"append|rephrase|shorten)\b",
    re.IGNORECASE,
)

CREATE_VERBS = re.compile(
    r"\b(cr[ée]{1,2}r?|cr[ée]{1,2}z|cr[ée]{1,2}s|r[ée]dig\w*|[ée]cri(?:s|re|vez)|g[ée]n[èé]r(?:e|er|ez)|"
    r"nouveau (?:document|fichier)|nouvelle (?:note|page|fiche)|"
    r"create|write|draft|generate|compose|new (?:document|file|note|page))\b",
    re.IGNORECASE,
)

NOT_MARKDOWN = (
    "Je ne peux créer que des documents au format Markdown (.md). Voulez-vous que je rédige celui-ci en Markdown ?"
)
NO_COLLECTION = "Vous n'avez aucune collection dans laquelle je puisse créer un document."


def documents_catalogue(documents: list[dict[str, Any]]) -> str:
    lines = []
    for document in documents:
        summary = f" - {document['summary']}" if document.get("summary") else ""
        where = f"collection « {document['collection_name']} »"
        lines.append(f"- id={document['document_id']} | « {document['name']} » ({where}){summary}")
    return "\n".join(lines)


def edit_clarification(documents: list[dict[str, Any]], candidate_ids: list[str]) -> str:
    named = [d for d in documents if d["document_id"] in candidate_ids] or documents
    options = "\n".join(f"- « {d['name']} » (collection « {d['collection_name']} »)" for d in named)
    return (
        "Plusieurs documents modifiables pourraient correspondre à votre demande. "
        f"Lequel voulez-vous modifier ?\n{options}"
    )


def collections_catalogue(collections: list[dict[str, Any]]) -> str:
    lines = []
    for collection in collections:
        description = f" - {collection['description']}" if collection.get("description") else ""
        lines.append(f"- id={collection['collection_id']} | « {collection['name']} »{description}")
    return "\n".join(lines) or "(none)"


def create_clarification(collections: list[dict[str, Any]], candidate_ids: list[str]) -> str:
    named = [c for c in collections if c["collection_id"] in candidate_ids] or collections
    options = "\n".join(f"- « {c['name']} »" for c in named)
    return f"Dans quelle collection voulez-vous créer ce document ?\n{options}"
