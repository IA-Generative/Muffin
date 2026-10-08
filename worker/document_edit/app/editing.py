"""One entry point per format, so the rest of the worker (the agent, the task) doesn't care whether
it is editing an ODT or a Markdown file."""

from typing import Literal

from app import markdown_editor, odt_editor
from app.edit_types import EditResult
from app.operations import Operation

Format = Literal["odt", "md"]


def outline(source: bytes, format_: Format) -> str:
    return (odt_editor if format_ == "odt" else markdown_editor).outline(source)


def apply_operations(source: bytes, operations: list[Operation], format_: Format) -> EditResult:
    return (odt_editor if format_ == "odt" else markdown_editor).apply_operations(source, operations)
