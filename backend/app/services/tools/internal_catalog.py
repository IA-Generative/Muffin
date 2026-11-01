"""The tools Muffin has in its own code (#343): exact calculation and dates.

They live in code, not in the database: a stable id, a name, a description, a schema, whether they change data, and the
function that runs them. Nothing here touches the network, and none changes data."""

import ast
import calendar
import math
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.agent.graph.services.time_tool import DEFAULT_TIMEZONE, _now

INTERNAL_PREFIX = "internal."


@dataclass(frozen=True)
class InternalTool:
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], str]
    side_effect: bool = False
    implemented: bool = True

    @property
    def ref(self) -> str:
        return f"{INTERNAL_PREFIX}{self.id}"


class ToolArgumentError(ValueError):
    """The arguments are wrong in a way the model can be told: said plainly, with no trace."""


# --- calculatrice ---

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
}
_MAX_EXPONENT = 1000
_MAX_NODES = 200


def evaluate(expression: str) -> float | int:
    """The value of an arithmetic expression, worked out from its syntax tree: numbers, + - * / // % **, parentheses,
    a few functions. Never `eval`: nothing else - a name, an attribute, a call to anything else - is accepted."""
    if len(expression) > 500:
        raise ToolArgumentError("L'expression est trop longue.")
    # A decimal comma ("3,5") is read as a point - unless there is a function in the expression, whose commas separate
    # its arguments ("max(3, 9)").
    prepared = expression if re.search(r"[a-zA-Z]", expression) else expression.replace(",", ".")
    try:
        tree = ast.parse(prepared.replace("^", "**").replace("×", "*").replace("÷", "/"), mode="eval")
    except SyntaxError as error:
        raise ToolArgumentError("L'expression n'est pas un calcul valide.") from error
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ToolArgumentError("L'expression est trop compliquée.")

    def walk(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise ToolArgumentError("L'exposant est trop grand.")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](walk(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and not node.keywords
        ):
            return _FUNCTIONS[node.func.id](*(walk(arg) for arg in node.args))
        raise ToolArgumentError(
            "Seuls les nombres, + - * / // % ** et quelques fonctions (sqrt, abs, round, min, max) sont permis."
        )

    try:
        value = walk(tree)
    except ZeroDivisionError as error:
        raise ToolArgumentError("Division par zéro.") from error
    except (OverflowError, ValueError, TypeError) as error:
        raise ToolArgumentError("Ce calcul n'a pas de résultat.") from error
    return value


def _calculatrice(arguments: dict[str, Any]) -> str:
    expression = str(arguments.get("expression", ""))
    value = evaluate(expression)
    shown = int(value) if isinstance(value, float) and value.is_integer() and abs(value) < 1e15 else value
    return f"{expression.strip()} = {shown}"


# --- calcul_dates ---

_OPERATIONS = ("jour_de_la_semaine", "ajouter", "ecart", "bornes_du_mois")
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def _day(value: Any, *, name: str) -> date:
    if value in (None, "", "aujourd'hui", "today"):
        return _now(DEFAULT_TIMEZONE).date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ToolArgumentError(f"« {name} » doit être une date AAAA-MM-JJ.") from error


def _calcul_dates(arguments: dict[str, Any]) -> str:
    operation = arguments.get("operation")
    if operation not in _OPERATIONS:
        raise ToolArgumentError(f"« operation » doit être l'une de : {', '.join(_OPERATIONS)}.")
    start = _day(arguments.get("date"), name="date")
    if operation == "jour_de_la_semaine":
        return f"{start.isoformat()} est un {_DAYS[start.weekday()]}."
    if operation == "ajouter":
        try:
            days = int(arguments.get("jours", 0))
        except (TypeError, ValueError) as error:
            raise ToolArgumentError("« jours » doit être un nombre entier.") from error
        if abs(days) > 366_000:
            raise ToolArgumentError("« jours » est trop grand.")
        try:
            result = start + timedelta(days=days)
        except OverflowError as error:
            raise ToolArgumentError("Cette date est hors des limites.") from error
        sign = "+" if days >= 0 else "-"
        return f"{start.isoformat()} {sign} {abs(days)} jours = {result.isoformat()} ({_DAYS[result.weekday()]})."
    if operation == "ecart":
        other = _day(arguments.get("autre_date"), name="autre_date")
        return f"Entre {start.isoformat()} et {other.isoformat()} : {(other - start).days} jours."
    last = calendar.monthrange(start.year, start.month)[1]
    month = f"{start.year}-{start.month:02d}"
    return f"{month} : du {month}-01 au {month}-{last:02d}."


INTERNAL_TOOLS: tuple[InternalTool, ...] = (
    InternalTool(
        id="calculatrice",
        name="calculatrice",
        description=(
            "Calcule exactement une expression arithmétique (montants, taux, pourcentages, moyennes à la main). "
            "À utiliser "
            "pour tout calcul plutôt que de le faire de tête. Opérateurs + - * / // % ** et sqrt, abs, round, min, max."
        ),
        input_schema={
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Ex. : 1250 * 1.2 - 80"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
        run=_calculatrice,
    ),
    InternalTool(
        id="calcul_dates",
        name="calcul_dates",
        description=(
            "Calculs sur les dates : jour de la semaine d'une date, date après N jours, écart en jours entre deux "
            "dates, "
            "premier et dernier jour d'un mois. Sans date, on part d'aujourd'hui."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": list(_OPERATIONS)},
                "date": {"type": "string", "description": "AAAA-MM-JJ ; aujourd'hui si absente"},
                "jours": {
                    "type": "integer",
                    "description": "Pour « ajouter » : nombre de jours (négatif pour reculer)",
                },
                "autre_date": {"type": "string", "description": "Pour « ecart » : AAAA-MM-JJ"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
        run=_calcul_dates,
    ),
)

BY_ID = {tool.id: tool for tool in INTERNAL_TOOLS}


def is_internal(ref: str) -> bool:
    return ref.startswith(INTERNAL_PREFIX)


def find(ref: str) -> InternalTool | None:
    return BY_ID.get(ref.removeprefix(INTERNAL_PREFIX)) if is_internal(ref) else None
