"""The editing agent (#168): turns a prompt into typed operations and applies them to the document.

A small LangGraph graph - plan, apply, and a bounded retry loop in which the reason a previous
answer was refused is shown back to the model:

    plan --(valid operations)--> apply --(applied)--> END
      ^                            |
      +--(refused, attempts left)--+--(refused, none left)--> END (EditFailedError)

The model never sees or writes the document itself, only its outline, and answers with operations
from a closed vocabulary (app/operations.py) - so what it can do is bounded, every change is
listable, and anything it doesn't name is left untouched."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger
from pydantic import ValidationError

from app.contract import PendingImage
from app.edit_types import OperationError
from app.editing import Format, apply_operations, outline
from app.operations import Operation, OperationList, SectionRef

# Takes chat messages ({"role", "content"}), returns the model's reply.
Llm = Callable[[list[dict[str, str]]], str]

_FORMAT_NAME = {"odt": "ODT (LibreOffice)", "md": "Markdown"}

SYSTEM_PROMPT = """\
Tu modifies un document existant à la demande d'un utilisateur. Tu ne vois pas le document \
lui-même mais son plan : ses sections, avec leurs paragraphes numérotés (¶1, ¶2…) et leurs \
tableaux (lignes L1, L2…). Tu réponds uniquement par des opérations d'édition, que l'on applique \
ensuite au document.

Réponds par un unique objet JSON, sans texte autour :
{"operations": [...], "pending_images": [...], "message": "..."}

Opérations disponibles (champ "op"). Une cible est une section, désignée par le texte exact de son \
titre ("heading", null pour le début du document avant le premier titre) et, si plusieurs titres \
ont le même texte, son "occurrence" (1 par défaut) :
- replace_paragraph : {"op": "replace_paragraph", "section": {"heading": "Contacts"}, "paragraph": 2, "text": "..."}
- insert_paragraph : {"op": "insert_paragraph", "section": {"heading": "Contacts"}, \
"after_paragraph": 1, "text": "..."} (after_paragraph : 0 = juste sous le titre, absent = en fin de section)
- delete_paragraph : {"op": "delete_paragraph", "section": {"heading": "Contacts"}, "paragraph": 2}
- insert_section : {"op": "insert_section", "after": {"heading": "Étapes"}, "level": 2, "title": "...", \
"paragraphs": ["..."]} (after absent = en fin de document ; la section est placée après la section \
indiquée et ses sous-sections)
- set_cell : {"op": "set_cell", "table": {"section": {"heading": "Matériel"}, "index": 1}, \
"row": 2, "column": 3, "text": "..."}
- insert_row : {"op": "insert_row", "table": {...}, "after_row": 2, "values": ["...", "..."]} \
(after_row absent = en bas ; values : un texte par colonne)
- delete_row : {"op": "delete_row", "table": {...}, "row": 2}
- insert_column : {"op": "insert_column", "table": {...}, "after_column": 1, "values": ["en-tête", "...", "..."]} \
(after_column absent = à droite ; values : un texte par ligne, en-tête compris)
- delete_column : {"op": "delete_column", "table": {...}, "column": 2}
- insert_table : {"op": "insert_table", "section": {"heading": "Contacts"}, "after_paragraph": 1, \
"rows": [["en-tête 1", "en-tête 2"], ["a", "b"]]}

Règles :
- Les opérations s'appliquent dans l'ordre, chacune sur le document tel que les précédentes l'ont \
laissé : après avoir inséré un paragraphe, les numéros suivants ont bougé d'un cran. Le plan, lui, \
montre le document de départ.
- Recopie les titres exactement comme dans le plan. N'invente aucune section ni aucun numéro qui \
n'existe pas.
- Ne modifie que ce que la demande vise, dans la langue et le ton du document. Pas de mise en forme \
Markdown dans un document ODT.
- Les listes, le code, les citations et les paragraphes marqués « non remplaçable » ne sont pas \
modifiables : ne les cible pas. Tu peux ajouter un paragraphe à côté.
- Tu ne peux ni générer ni insérer d'image. Si une image serait utile, décris-la dans \
"pending_images" : [{"description": "...", "section": {"heading": "..."}, "after_paragraph": 1}] \
(section et after_paragraph facultatifs) ; l'utilisateur la déposera lui-même.
- "message" : une phrase pour l'utilisateur. Si la demande est impossible avec ces opérations, \
laisse "operations" vide et explique pourquoi dans "message".
"""


class EditFailedError(Exception):
    """The agent couldn't produce an applicable edit. `message` is fit to show the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class AgentOutcome:
    # The edited file - the unchanged source when the model made no operation.
    data: bytes
    summary: list[str]
    message: str
    pending_images: list[PendingImage] = field(default_factory=list)
    edited: bool = False
    attempts: int = 1


class _State(TypedDict, total=False):
    source: bytes
    format: Format
    prompt: str
    outline: str
    attempt: int
    messages: list[dict[str, str]]
    reply: str
    feedback: str | None
    operations: list[Operation]
    pending_images: list[PendingImage]
    message: str
    data: bytes
    summary: list[str]


def _json_object(reply: str) -> Any:
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap the object in a sentence despite the instruction.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _describe(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in error.errors()[:5]]
    return "; ".join(parts)


def _parse_reply(reply: str) -> tuple[list[Operation], list[PendingImage], str]:
    """The model's JSON as operations, pending images and its message - raises ValueError with a
    description meant for the model when anything in it is unusable."""
    try:
        payload = _json_object(reply)
    except json.JSONDecodeError as error:
        raise ValueError(f"ta réponse n'est pas un JSON valide ({error.msg}).") from error
    if not isinstance(payload, dict):
        raise ValueError("ta réponse doit être un objet JSON avec les clés operations, pending_images et message.")
    try:
        operations = OperationList.validate_python(payload.get("operations") or [])
    except ValidationError as error:
        raise ValueError(f"les opérations sont invalides : {_describe(error)}") from error

    images: list[PendingImage] = []
    for index, raw in enumerate(payload.get("pending_images") or [], start=1):
        if not isinstance(raw, dict) or not str(raw.get("description", "")).strip():
            raise ValueError("chaque élément de pending_images doit avoir une description.")
        try:
            section = SectionRef.model_validate(raw["section"]) if raw.get("section") else None
            images.append(
                PendingImage(
                    id=f"img-{index}",
                    description=str(raw["description"]).strip(),
                    section=section,
                    after_paragraph=raw.get("after_paragraph"),
                )
            )
        except ValidationError as error:
            raise ValueError(f"pending_images est invalide : {_describe(error)}") from error
    return operations, images, str(payload.get("message") or "").strip()


def _build_graph(llm: Llm, max_attempts: int):
    def plan(state: _State) -> _State:
        attempt = state["attempt"] + 1
        messages = state["messages"]
        if state.get("feedback"):
            # Show the model its own refused answer and why, so it corrects rather than repeats.
            messages = [
                *messages,
                {"role": "assistant", "content": state["reply"]},
                {
                    "role": "user",
                    "content": f"Ta réponse n'a pas pu être appliquée : {state['feedback']}\n"
                    "Corrige-la et renvoie la liste complète des opérations, en JSON uniquement.",
                },
            ]
        reply = llm(messages)
        update: _State = {"attempt": attempt, "reply": reply, "feedback": None}
        try:
            operations, images, message = _parse_reply(reply)
        except ValueError as problem:
            logger.warning(f"Attempt {attempt}: unusable reply - {problem}")
            return {**update, "feedback": str(problem)}
        logger.info(f"Attempt {attempt}: {len(operations)} operation(s), {len(images)} pending image(s)")
        return {**update, "operations": operations, "pending_images": images, "message": message}

    def apply(state: _State) -> _State:
        try:
            result = apply_operations(state["source"], state["operations"], state["format"])
        except OperationError as error:
            logger.warning(f"Attempt {state['attempt']}: {error}")
            return {"feedback": str(error)}
        return {"feedback": None, "data": result.data, "summary": result.summary}

    def after_plan(state: _State) -> str:
        if state.get("feedback"):
            return "retry" if state["attempt"] < max_attempts else "fail"
        # Nothing to apply: the model declined or found nothing to change - the message says why.
        return "apply" if state["operations"] else "done"

    def after_apply(state: _State) -> str:
        if state.get("feedback"):
            return "retry" if state["attempt"] < max_attempts else "fail"
        return "done"

    graph = StateGraph(_State)
    graph.add_node("plan", plan)
    graph.add_node("apply", apply)
    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", after_plan, {"apply": "apply", "retry": "plan", "fail": END, "done": END})
    graph.add_conditional_edges("apply", after_apply, {"retry": "plan", "fail": END, "done": END})
    return graph.compile()


def run_edit_agent(
    source: bytes, format_: Format, prompt: str, llm: Llm, *, max_attempts: int = 3, max_outline_chars: int = 60000
) -> AgentOutcome:
    document_outline = outline(source, format_)
    if len(document_outline) > max_outline_chars:
        raise EditFailedError(
            f"Le document est trop volumineux pour être modifié en une fois "
            f"({len(document_outline)} caractères de plan, maximum {max_outline_chars})."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Document au format {_FORMAT_NAME[format_]}. Plan :\n\n{document_outline}\n\n"
            f"Demande de l'utilisateur :\n{prompt}",
        },
    ]
    initial: _State = {
        "source": source,
        "format": format_,
        "prompt": prompt,
        "outline": document_outline,
        "attempt": 0,
        "messages": messages,
        "feedback": None,
    }
    final: _State = _build_graph(llm, max_attempts).invoke(initial)

    if final.get("feedback"):
        raise EditFailedError(
            f"Je n'ai pas réussi à produire une modification applicable après {final['attempt']} tentative(s) : "
            f"{final['feedback']}"
        )
    operations = final.get("operations") or []
    return AgentOutcome(
        data=final.get("data", source),
        summary=final.get("summary", []),
        message=final.get("message", ""),
        pending_images=final.get("pending_images", []),
        edited=bool(operations),
        attempts=final["attempt"],
    )
